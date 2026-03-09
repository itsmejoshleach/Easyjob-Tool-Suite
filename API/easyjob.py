# Easyjob API Helper

# Important Info & Definitions
# Barcode: Rental-Point Style Barcode (Device specific), e.g. BP2/205
# Device_Id: EJ Device specific number (for individually barcoded items)
# Item_Id: EJ generic item number (for generic / non-barcoded items)
# job_Id: Internal EJ Job ID
# Job_No: CT Job ID 


import requests
import os
from typing import Optional, Dict, Any
from urllib.parse import quote
import urllib3
from dotenv import load_dotenv, set_key, find_dotenv

# Suppress SSL warnings (for self-signed certificates)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load .env
dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

BASE_URL: Optional[str] = os.getenv("EJ_BASE_URL")
USERNAME: Optional[str] = os.getenv("EJ_USERNAME")
PASSWORD: Optional[str] = os.getenv("EJ_PASSWORD")
TOKEN: Optional[str] = os.getenv("EJ_Access_Token")
VERIFY_CERT = False  # default for testing
TIMEOUT = 10

# Helpers

def _warn(message):
    print("\033[93m {}\033[00m".format(f"[WARN] - {message}"))

def _log(message):
    print("\033[95m {}\033[00m".format(f"[LOG] - {message}"))

def _error(message):
    print("\033[91m {}\033[00m".format(f"[ERROR] - {message}"))
    raise RuntimeError(message)

def _saveTOKEN(token: str): 
    # Save token to .env
    global TOKEN
    TOKEN = token
    if dotenv_path:
        set_key(dotenv_path, "EJ_Access_Token", token)

def _headers() -> Dict[str, str]:
    # Returns Headers (auth with token, if valid)
    if not TOKEN:
        _error("No token loaded. Call authenticate() first.")
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def _request_with_auto_reauth(method: str, path: str, **kwargs):
    # Does a request, and auto reauths the token using username & password creds - Returns request response
    url = f"{BASE_URL}{path}"
    try:
        response = requests.request(method, url, headers=_headers(), timeout=TIMEOUT, verify=VERIFY_CERT, **kwargs)
        if response.status_code == 401:
            authenticate()  # refresh token
            response = requests.request(method, url, headers=_headers(), timeout=TIMEOUT, verify=VERIFY_CERT, **kwargs)
        
        # Check for specific error codes before raising
        if response.status_code == 500:
            _error(f"API server error (500) for endpoint: {path}")
        
        response.raise_for_status()
        
        # Try to parse JSON response
        try:
            json_data = response.json()
            # Check if response is just an error code like "0"
            if json_data == "0" or json_data == 0:
                _error(f"API returned error code 0 - item/barcode not found or invalid")
            return json_data
        except ValueError:
            _error(f"API returned invalid JSON: {response.text[:200]}")
            
    except requests.exceptions.HTTPError as e:
        _error(f"HTTP Error {e.response.status_code}: {e.response.reason} for {path}")
    except requests.exceptions.RequestException as exception:
        _error(f"EasyJob request failed: {exception}")

def _convert_barcode_to_device_id(barcode: str) -> int:
    # Take Warehouse barcode and convert to EJ device ID
    devices = get_device_info(barcode)

    if not devices:
        _error(f"No device found for barcode {barcode}")

    device_id = devices[0].get("Id")
    if not device_id:
        _error("Device Id missing in response")

    return int(device_id)


def _convert_jobno_to_jobid(search_term: str) -> int:
    # Convert a job number or job name to the EasyJob Job Id.
    jobs = get_job_info(search_term)
    
    if not jobs:
        _error(f"No job found matching '{search_term}'")
    
    # Assuming the first match is the one we want
    job_id = jobs[0].get('Id')
    if not job_id:
        _error(f"Job Id not found in API response for '{search_term}'")
    
    return int(job_id)


def _get(path: str, params=None):
    # HTTP GET request
    return _request_with_auto_reauth("GET", path, params=params)

def _post(path: str, payload=None):
    # HTTP POST Request
    return _request_with_auto_reauth("POST", path, json=payload)


# Authentication

def authenticate() -> str: 
    # Authenticate using username/password and save token to .env
    global TOKEN
    if not USERNAME or not PASSWORD:
        _error("Username and password required for authentication")

    url = f"{BASE_URL}/token"
    data = {"grant_type": "password", "username": USERNAME, "password": PASSWORD}
    response = requests.post(url, data=data, timeout=TIMEOUT, verify=VERIFY_CERT)
    response.raise_for_status()
    token = response.json()["access_token"]
    _saveTOKEN(token)
    return token

def quick_login(base_url: str = None, username: str = None, password: str = None, verify_cert: bool = False): 
    # Load configuration (optional overrides), use existing token if available
    global BASE_URL, USERNAME, PASSWORD, VERIFY_CERT
    if base_url:
        BASE_URL = base_url.rstrip("/")
    if username:
        USERNAME = username
    if password:
        PASSWORD = password
    VERIFY_CERT = verify_cert

    # Use existing token if present, otherwise authenticate
    if not TOKEN:
        authenticate()

# Item Functions

def get_items_in_job(jobno: str):
    # List items on job
    return _get(f"/api.json/Items/BillOfItems/?id={jobno}")

def get_device_list(item_id: str, search_text: str = ""):
    # Get all devices for an item type (stock levels)
    return _get(f"/api.json/Items/DeviceList/?id={item_id}&searchtext={search_text}")

# Info Functions

def get_device_info(devicebarcode: str, debug=False):
    # List Device info (Barcoded Devices)
    # URL encode the barcode to handle special characters like /
    encoded_barcode = quote(devicebarcode, safe='')
    endpoint = f"/api.json/Common/BarcodeSearch?id={encoded_barcode}"
    
    if debug:
        _log(f"Searching for barcode: {devicebarcode}")
        _log(f"Encoded as: {encoded_barcode}")
        _log(f"Full endpoint: {BASE_URL}{endpoint}")
    
    result = _get(endpoint)
    
    if debug:
        _log(f"API Response: {result}")
    
    return result

def get_job_info(searchname: str):
    # Gets info on a job
    # URL encode the search term to handle special characters
    encoded_search = quote(f"*{searchname}", safe='*')
    return _get(f"/api.json/Jobs/List/?style=List&searchtext={encoded_search}")

# Other

def test_connection(): 
    # Simple test to check API connectivity and authentication - Returns server info if token works
    return _get("/api.json/Common/GetGlobalWebSettings")


# Print data
def print_items_in_job(searchterm: str):
    job = get_job_info(searchterm)
    jobno = int(job[0]['Id'])
    jobitems = get_items_in_job(jobno)
    jobitems_dict = {}
    for item in jobitems:
        item_id = item['IdST2J']  # unique identifier for each item
        jobitems_dict[item_id] = {
            'group': item['Group'],
            'name': item['Caption'],
            'category': item['Category'],
            'quantity': item['Qty'],
            'days': item.get('Days', 1)  # include Days if needed, default 1
        }
    return jobitems_dict
