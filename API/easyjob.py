# EasyJob API Helper

# Definitions:
# Barcode    - Rental-Point style barcode (device-specific), e.g. BP2/205
# Device_Id  - EJ device-specific number (individually barcoded items)
# Item_Id    - EJ generic item number (non-barcoded / generic items)
# Job_Id     - Internal EJ job ID
# Job_No     - CT job ID

import requests
import os
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from urllib.parse import quote
import urllib3
from dotenv import load_dotenv, set_key, find_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# -- Config --

dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

BASE_URL: Optional[str] = os.getenv("EJ_BASE_URL")
USERNAME: Optional[str] = os.getenv("EJ_USERNAME")
PASSWORD: Optional[str] = os.getenv("EJ_PASSWORD")
TOKEN: Optional[str] = os.getenv("EJ_Access_Token")
VERIFY_CERT = False
TIMEOUT = 10


# -- Logging --

def _warn(message):
    print("\033[93m[WARN] {}\033[00m".format(message))

def _log(message):
    print("\033[95m[LOG] {}\033[00m".format(message))

def _error(message):
    print("\033[91m[ERROR] {}\033[00m".format(message))
    raise RuntimeError(message)


# -- Internal Helpers --

def _save_token(token: str):
    global TOKEN
    TOKEN = token
    if dotenv_path:
        set_key(dotenv_path, "EJ_Access_Token", token)

def _headers() -> Dict[str, str]:
    if not TOKEN:
        _error("No token loaded. Call authenticate() first.")
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def _request(method: str, path: str, **kwargs):
    # Makes a request, auto-reauthenticates on 401
    url = f"{BASE_URL}{path}"
    try:
        response = requests.request(method, url, headers=_headers(), timeout=TIMEOUT, verify=VERIFY_CERT, **kwargs)
        if response.status_code == 401:
            authenticate()
            response = requests.request(method, url, headers=_headers(), timeout=TIMEOUT, verify=VERIFY_CERT, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        _error(f"EasyJob request failed: {e}")

def _get(path: str, params=None):
    return _request("GET", path, params=params)

def _post(path: str, payload=None):
    return _request("POST", path, json=payload)

def _convert_barcode_to_device_id(barcode: str) -> int:
    devices = get_device_info(barcode)
    if not devices:
        _error(f"No device found for barcode {barcode}")
    device_id = devices[0].get("Id")
    if not device_id:
        _error("Device Id missing in response")
    return int(device_id)

def _convert_jobno_to_jobid(search_term: str) -> int:
    jobs = get_job_info(search_term)
    if not jobs:
        _error(f"No job found matching '{search_term}'")
    job_id = jobs[0].get("Id")
    if not job_id:
        _error(f"Job Id not found for '{search_term}'")
    return int(job_id)


# -- Authentication --

def authenticate() -> str:
    global TOKEN
    if not USERNAME or not PASSWORD:
        _error("Username and password required for authentication")
    url = f"{BASE_URL}/token"
    data = {"grant_type": "password", "username": USERNAME, "password": PASSWORD}
    response = requests.post(url, data=data, timeout=TIMEOUT, verify=VERIFY_CERT)
    response.raise_for_status()
    token = response.json()["access_token"]
    _save_token(token)
    return token

def quick_login(base_url: str = None, username: str = None, password: str = None, verify_cert: bool = False):
    # Load config overrides, use existing token if available
    global BASE_URL, USERNAME, PASSWORD, VERIFY_CERT
    if base_url:
        BASE_URL = base_url.rstrip("/")
    if username:
        USERNAME = username
    if password:
        PASSWORD = password
    VERIFY_CERT = verify_cert
    if not TOKEN:
        authenticate()


# -- Item Functions --

def get_items_in_job(job_id: str):
    # Returns list of items on a job
    return _get(f"/api.json/Items/BillOfItems/?id={job_id}")

def get_all_items(searchtext: str = ""):
    # Returns full item list, optionally filtered by search text.
    # Uses inline URL to avoid requests double-encoding the * wildcard.
    if searchtext:
        encoded = quote(searchtext, safe="*")
        return _get(f"/api.json/Items/List/?searchtext={encoded}")
    return _get("/api.json/Items/List/")

def get_all_items_full():
    # Returns complete EJ item catalogue with all fields needed for sync.
    # type=view includes non-barcoded items; style=List gives flat list.
    return _get("/api.json/Items/List/?searchtext=*&type=view&style=List&IdUserFilter=0")

def get_item_details(item_id: int):
    # Returns detailed info for a single item, including RentalInventory (total active owned count)
    return _get(f"/api.json/Items/Details/?id={item_id}")

def get_item_accessories(item_id: int):
    # Returns linked/accessory items for a given stock type
    return _get(f"/api.json/Items/AccessoryItems/?id={item_id}")

def get_item_availability(item_id: int, start_date: str = None, end_date: str = None, stock_id: int = None):
    # Returns availability data for an item.
    # EJ requires startdate + enddate — defaults to now if not provided.
    # Dates must be ISO format: 2025-01-01T00:00:00.000Z
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    params = {
        "startdate": start_date or now,
        "enddate":   end_date   or now,
    }
    if stock_id:
        params["stock"] = stock_id
    return _get(f"/api.json/Items/Avail/{item_id}", params=params)


# -- Info Functions --

def get_device_info(device_barcode: str, debug: bool = False):
    # Returns device info for a barcoded item (RP barcode e.g. BP2/205)
    # URL-encodes the barcode to handle special characters like /
    encoded = quote(device_barcode, safe="")
    endpoint = f"/api.json/Common/BarcodeSearch?id={encoded}"
    if debug:
        _log(f"Barcode: {device_barcode}  ->  encoded: {encoded}")
        _log(f"Endpoint: {BASE_URL}{endpoint}")
    result = _get(endpoint)
    if debug:
        _log(f"Response: {result}")
    return result

def get_calendar(start_date: str, days: int = 35):
    # Fetch calendar entries from EJ dashboard.
    # start_date: "YYYY-MM-DD", days: how many days ahead to fetch.
    return _get(f"/api.json/dashboard/calendar/?days={days}&startdate={start_date}")
    # Returns all individual devices for a given item type (used for stock counts)
    return _get(f"/api.json/Items/DeviceList/?id={item_id}&searchtext={search_text}")

def get_job_info(search_name: str):
    # Returns job info matching a search term / job number
    # URL-encodes the search term to handle special characters
    encoded = quote(f"*{search_name}", safe="*")
    return _get(f"/api.json/Jobs/List/?style=List&searchtext={encoded}")

def test_connection():
    # Quick check - returns server info if token is valid
    return _get("/api.json/Common/GetGlobalWebSettings")


# -- Stock Check --

def get_stock_summary(item_id: int, start_date: str = None, end_date: str = None):
    # Returns a dict showing how many of an item are:
    #   - In warehouse (available)
    #   - Out on jobs (booked)
    #   - In workshop / service (if tracked as a separate stock location)
    #
    # Uses current date/time if no dates provided.
    # Note: EasyJob's Avail endpoint returns Total and Booked counts.
    # "Workshop" items may appear as a separate stock location depending on your EJ setup.

    if not start_date:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        start_date = now
        end_date = now

    avail = get_item_availability(item_id, start_date=start_date, end_date=end_date)

    if not avail:
        _error(f"No availability data returned for item {item_id}")

    # EJ Avail response fields (may vary by version):
    # Avail       - quantity currently available (in warehouse)
    # Booked      - quantity out on active jobs
    # Total       - total owned quantity
    # Service     - quantity in workshop/service (if WMS module active)
    total   = avail.get("Total", 0)
    booked  = avail.get("Booked", 0)
    service = avail.get("Service", 0)    # workshop / QA / repair — requires WMS module
    avail_qty = avail.get("Avail", total - booked - service)

    return {
        "item_id":    item_id,
        "total":      total,
        "warehouse":  avail_qty,
        "on_jobs":    booked,
        "workshop":   service,
        "raw":        avail     # full response for debugging
    }

def get_stock_summary_by_name(search_name: str, start_date: str = None, end_date: str = None):
    # Convenience wrapper - looks up item by name then returns stock summary
    items = get_all_items(searchtext=search_name)
    if not items:
        _error(f"No items found matching '{search_name}'")

    results = []
    for item in items:
        item_id = item.get("Id")
        name = item.get("Caption", str(item_id))
        if not item_id:
            continue
        summary = get_stock_summary(item_id, start_date=start_date, end_date=end_date)
        summary["name"] = name
        results.append(summary)
    return results

def print_stock_summary(search_name: str):
    # Prints a readable stock report for an item
    results = get_stock_summary_by_name(search_name)
    for r in results:
        print(f"\n  {r['name']} (ID: {r['item_id']})")
        print(f"    Total:     {r['total']}")
        print(f"    Warehouse: {r['warehouse']}")
        print(f"    On Jobs:   {r['on_jobs']}")
        print(f"    Workshop:  {r['workshop']}")


# -- Job Item Helpers --

def print_items_in_job(search_term: str):
    # Prints a dict of all items on a job
    job = get_job_info(search_term)
    job_id = int(job[0]["Id"])
    job_items = get_items_in_job(job_id)

    result = {}
    for item in job_items:
        item_id = item["IdST2J"]
        result[item_id] = {
            "group":    item["Group"],
            "name":     item["Caption"],
            "category": item["Category"],
            "quantity": item["Qty"],
            "days":     item.get("Days", 1)
        }
    return result
