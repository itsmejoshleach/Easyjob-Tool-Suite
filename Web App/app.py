import sys
import os
import csv
import re
import json
import threading
import requests
import pandas as pd
from datetime import datetime
from functools import wraps
from cryptography.fernet import Fernet, InvalidToken
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from PIL import Image, ImageDraw, ImageFont

# Add parent directory to path to import API module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from API import easyjob as ej

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB - handles large EJ item exports
app.secret_key = os.getenv("SECRET_KEY", "change-me-in-prod")

# -- Encryption --
# EJ passwords are stored encrypted in users.json.
# FIELD_ENCRYPT_KEY in .env must be a valid Fernet key.
# Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

def _get_fernet() -> Fernet:
    key = os.getenv("FIELD_ENCRYPT_KEY", "")
    if not key:
        raise RuntimeError("FIELD_ENCRYPT_KEY not set in .env - cannot encrypt/decrypt EJ passwords.")
    return Fernet(key.encode())

def encrypt_field(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()

def decrypt_field(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return ""  # wrong key or corrupt - return empty rather than crash


# -- Config --

ITEMS_CSV  = "./items.csv"
CUSTOM_CSV = "./custom_barcodes.csv"

BARCODE_DIR        = "static/barcode_images"
LABEL_DIR          = "static/labels"
CUSTOM_BARCODE_DIR = "static/custom_barcode_images"
CUSTOM_LABEL_DIR   = "static/custom_labels"

BARCODE_API   = "https://barcodeapi.org/api/code128/{}"
FONT_PATH     = "./monofonto rg.otf"
WATCHERS_FILE = "./job_watchers.json"

CSV_COLUMNS    = ["Item Name", "Item Description / Alternate Names", "Barcode Number", "Barcode Image URL", "Barcode Image"]
CUSTOM_COLUMNS = ["Name", "Barcode", "Barcode Image URL", "Barcode Image"]
PROFILES_FILE  = "./item_profiles.json"   # stores More Info content keyed by item name
USERS_FILE     = "./users.json"

# Label config
LABEL_WIDTH_MM       = 50
LABEL_HEIGHT_MM      = 25
DPI                  = 300
TEXT_HEIGHT_FRACTION = 1 / 3
PADDING_MM           = 0.5

for d in [BARCODE_DIR, LABEL_DIR, CUSTOM_BARCODE_DIR, CUSTOM_LABEL_DIR]:
    os.makedirs(d, exist_ok=True)


# -- Utils --

def mm_to_px(mm): # Convert mm to px based on DPI
    return int((mm / 25.4) * DPI)

LABEL_WIDTH  = mm_to_px(LABEL_WIDTH_MM)
LABEL_HEIGHT = mm_to_px(LABEL_HEIGHT_MM)
PADDING      = mm_to_px(PADDING_MM)
TEXT_HEIGHT  = int(LABEL_HEIGHT * TEXT_HEIGHT_FRACTION)

def sanitize_filename(name): # Remove invalid chars
    return re.sub(r'[\\/:*?"<>| ]+', '_', name).strip()

def ensure_csv(path, columns): # Check if csv file exists
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(columns)

# -- Auth --

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            return render_template("403.html", page=None), 403
        return f(*args, **kwargs)
    return decorated


def ej_call(fn, *args, **kwargs):
    # Wrapper for EJ API calls that handles token expiry.
    # On RuntimeError (which is what easyjob raises on 401 after retry),
    # clears the cached session token and re-authenticates once.
    try:
        return fn(*args, **kwargs)
    except RuntimeError as e:
        if "401" in str(e) or "request failed" in str(e).lower():
            session.pop("ej_token", None)
            ej.TOKEN = None
            if ej_login():
                return fn(*args, **kwargs)
        raise

def ej_login() -> bool:
    # Authenticates using the current session user's EJ credentials.
    # Caches the token in session["ej_token"] so we only re-authenticate when needed.
    # Never reuses another user's token - token is always tied to the session.
    # Returns False if the session has no EJ credentials configured.
    ej_user  = session.get("ej_username", "")
    ej_pass  = session.get("ej_password", "")
    if not ej_user or not ej_pass:
        ej.TOKEN = None  # ensure no stale token from another user bleeds through
        return False

    cached_token = session.get("ej_token")
    if cached_token:
        # Reuse cached token - set it on the module so API calls use it
        ej.TOKEN = cached_token
        return True

    # No cached token - authenticate and cache the result
    try:
        ej.quick_login(username=ej_user, password=ej_pass)
        session["ej_token"] = ej.TOKEN  # persist in session cookie
        return True
    except Exception:
        return False


# -- Load Items --

def load_profiles(): # Load item profiles
    if not os.path.exists(PROFILES_FILE):
        return {}
    with open(PROFILES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_profiles(profiles): # save item profiles
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)

def wildcard_to_regex(query): # Convert wildcard to regex
    return re.escape(query).replace("\\*", ".*")

PAGE_SIZE = 25

def load_items(query="", page=1): # Load items with search and pagination
    ensure_csv(ITEMS_CSV, CSV_COLUMNS)
    df = pd.read_csv(ITEMS_CSV, dtype=str).fillna("")
    df["Item Name"] = df["Item Name"].str.strip()
    df["Item Description / Alternate Names"] = df["Item Description / Alternate Names"].str.strip()
    df["Barcode Number"] = df["Barcode Number"].str.strip()

    if query:
        rx = wildcard_to_regex(query)
        df = df[
            df["Item Name"].str.contains(rx, case=False, regex=True) |
            df["Item Description / Alternate Names"].str.contains(rx, case=False, regex=True) |
            df["Barcode Number"].str.contains(rx, case=False, regex=True)
        ]

    total       = len(df)
    total_pages = max(1, -(-total // PAGE_SIZE))  # ceiling division
    page        = max(1, min(page, total_pages))
    df_page     = df.iloc[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    profiles = load_profiles()
    items = []
    for _, row in df_page.iterrows():
        name = row["Item Name"]
        if not name:
            continue
        safe = sanitize_filename(name)
        label_path = f"labels/{safe}_label.png"
        items.append({
            "name":        name,
            "description": row["Item Description / Alternate Names"],
            "barcode":     row["Barcode Number"],
            "label":       label_path if os.path.exists(os.path.join("static", label_path)) else None,
            "photo_url":   profiles.get(name, {}).get("photo_url", ""),
            "profile":     None,
        })
    return items, total, page, total_pages

def load_custom_barcodes(query=""): # load custom barcodes
    ensure_csv(CUSTOM_CSV, CUSTOM_COLUMNS)
    df = pd.read_csv(CUSTOM_CSV, dtype=str).fillna("")
    df["Name"]    = df["Name"].str.strip()
    df["Barcode"] = df["Barcode"].str.strip()

    if query:
        rx = wildcard_to_regex(query)
        df = df[
            df["Name"].str.contains(rx, case=False, regex=True) |
            df["Barcode"].str.contains(rx, case=False, regex=True)
        ]

    items = []
    for _, row in df.iterrows():
        name = row["Name"]
        if not name:
            continue
        safe       = sanitize_filename(name)
        label_path = f"custom_labels/{safe}_label.png"
        if not os.path.exists(os.path.join("static", label_path)):
            continue
        items.append({
            "name":    name,
            "barcode": row["Barcode"],
            "label":   label_path
        })
    return items


# -- Barcode / Label Generation --

def generate_barcode(barcode, name, custom=False): # Generate barcode
    safe     = sanitize_filename(name)
    dir_path = CUSTOM_BARCODE_DIR if custom else BARCODE_DIR
    path     = os.path.join(dir_path, f"{safe}.png")
    r = requests.get(BARCODE_API.format(barcode), timeout=10)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    return path

def create_label(barcode_img_path, name, custom=False): # take barcode and text and create label
    safe     = sanitize_filename(name)
    dir_path = CUSTOM_LABEL_DIR if custom else LABEL_DIR
    out_path = os.path.join(dir_path, f"{safe}_label.png")

    label   = Image.new("1", (LABEL_WIDTH, LABEL_HEIGHT), 1)
    barcode = Image.open(barcode_img_path).convert("1")

    max_w = LABEL_WIDTH - 2 * PADDING
    max_h = LABEL_HEIGHT - TEXT_HEIGHT - 2 * PADDING
    bw, bh = barcode.size
    scale   = min(max_w / bw, max_h / bh)
    barcode = barcode.resize((int(bw * scale), int(bh * scale)), Image.LANCZOS)
    label.paste(barcode, ((LABEL_WIDTH - barcode.width) // 2, PADDING))

    draw      = ImageDraw.Draw(label)
    font_size = 80
    font      = ImageFont.truetype(FONT_PATH, font_size)
    while draw.textbbox((0, 0), name, font=font)[2] > LABEL_WIDTH - 10:
        font_size -= 2
        font = ImageFont.truetype(FONT_PATH, font_size)

    bbox   = draw.textbbox((0, 0), name, font=font)
    text_x = (LABEL_WIDTH - (bbox[2] - bbox[0])) // 2
    text_y = LABEL_HEIGHT - TEXT_HEIGHT + (TEXT_HEIGHT - (bbox[3] - bbox[1])) // 2
    draw.text((text_x, text_y), name, font=font, fill=0)
    label.save(out_path)
    return out_path


# -- Routes --

@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        query = request.form.get("search", "").strip()
        page  = 1
    else:
        query = request.args.get("q", "").strip()
        page  = int(request.args.get("page", 1))

    items, total, page, total_pages = load_items(query, page)
    return render_template("index.html",
        items=items, query=query, page_num=page,
        total=total, total_pages=total_pages,
        page_size=PAGE_SIZE, page="items")


@app.route("/item_profile", methods=["GET"])
@login_required
def item_profile(): # GET endpoint for fetching item profile data
    # Returns JSON profile for the More Info modal.
    # Resolves item name → EJ item ID → details + accessories, then generates
    # AI description and how-to via Claude API.
    item_name = request.args.get("name", "").strip()
    barcode   = request.args.get("barcode", "").strip()
    if not item_name:
        return jsonify({"error": "No item name provided"}), 400

    profile = {
        "name":        item_name,
        "ej_details":  None,
        "accessories": [],
        "ai_content":  None,
        "image_query": item_name,
    }

    # ## Resolve EJ details via barcode or name search
    ej_ok = ej_login()
    if ej_ok:
        try:
            # Try barcode first (faster, exact)
            if barcode:
                device = _unwrap(ej.get_device_info(barcode))
                if device:
                    item_id = (device.get("Additional") or {}).get("IdStockType") or device.get("IdStockType")
                    if item_id:
                        details = _unwrap(ej.get_item_details(int(item_id)))
                        profile["ej_details"] = details
            # Fallback: name search
            if not profile["ej_details"]:
                found = ej.get_all_items(searchtext=f"*{item_name}*")
                if found:
                    item_id = found[0].get("Id") or found[0].get("ID")
                    if item_id:
                        details = _unwrap(ej.get_item_details(int(item_id)))
                        profile["ej_details"] = details
        except Exception:
            pass

        # ## Fetch accessories
        if profile["ej_details"]:
            try:
                raw_id = profile["ej_details"].get("ID") or profile["ej_details"].get("Id") or profile["ej_details"].get("IdStockType")
                if raw_id:
                    acc = ej.get_item_accessories(int(raw_id))
                    if isinstance(acc, list):
                        profile["accessories"] = [
                            {"name": a.get("Caption", ""), "number": a.get("Number", "")}
                            for a in acc if a.get("Caption")
                        ]
                    else:
                        profile["accessories_debug"] = f"Unexpected response type: {type(acc).__name__} - {str(acc)[:200]}"
                else:
                    profile["accessories_debug"] = f"Could not find item ID in ej_details keys: {list(profile['ej_details'].keys())}"
            except Exception as e:
                profile["accessories_debug"] = f"Exception: {e}"

    # ## Load saved profile content (manually edited via More Info popup)
    profiles    = load_profiles()
    saved       = profiles.get(item_name, {})
    details     = profile["ej_details"] or {}
    ej_comment  = details.get("Comment", "").strip()

    # Use explicit None checks - empty string is a valid saved value and must not fall through
    desc = saved["description"] if "description" in saved else (ej_comment or "")
    profile["ai_content"] = {
        "description": desc,
        "how_to":      saved.get("how_to") or [],
        "photo_url":   saved.get("photo_url") or "",
    }

    return jsonify(profile)


@app.route("/save_profile", methods=["POST"])
@login_required
def save_profile():
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "Missing item name"}), 400

    name     = data["name"].strip()
    profiles = load_profiles()
    profiles[name] = {
        "description": data.get("description", "").strip(),
        "how_to":      [s.strip() for s in data.get("how_to", []) if s.strip()],
        "photo_url":   data.get("photo_url", "").strip(),
    }
    save_profiles(profiles)
    return jsonify({"ok": True})

@app.route("/add", methods=["POST"])
@login_required
def add_item():
    name    = request.form.get("name", "").strip()
    desc    = request.form.get("description", "").strip()
    barcode = request.form.get("barcode", "").strip()
    if not name or not barcode:
        return "Missing fields", 400
    ensure_csv(ITEMS_CSV, CSV_COLUMNS)
    with open(ITEMS_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([name, desc, barcode, "", ""])
    barcode_path = generate_barcode(barcode, name, custom=False)
    create_label(barcode_path, name, custom=False)
    return redirect(url_for("index"))


# -- Custom Barcodes --

@app.route("/custom_barcodes", methods=["GET", "POST"])
@login_required
def custom_barcodes():
    query = ""
    if request.method == "POST":
        query = request.form.get("search", "").strip()
        if request.form.get("clear") == "1":
            items = load_custom_barcodes()
            for i in items:
                try:
                    os.remove(os.path.join(CUSTOM_BARCODE_DIR, sanitize_filename(i["name"]) + ".png"))
                    os.remove(os.path.join(CUSTOM_LABEL_DIR,   sanitize_filename(i["name"]) + ".png"))
                except FileNotFoundError:
                    pass
            with open(CUSTOM_CSV, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(CUSTOM_COLUMNS)
            return render_template("custom_barcodes.html", items=[], query="", page="custom")
    items = load_custom_barcodes(query)
    return render_template("custom_barcodes.html", items=items, query=query, page="custom")

@app.route("/add_custom_barcode", methods=["POST"])
@login_required
def add_custom_barcode():
    name    = request.form.get("name", "").strip()
    barcode = request.form.get("barcode", "").strip()
    if not name or not barcode:
        return "Missing fields", 400
    ensure_csv(CUSTOM_CSV, CUSTOM_COLUMNS)
    with open(CUSTOM_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([name, barcode, "", ""])
    barcode_path = generate_barcode(barcode, name, custom=True)
    create_label(barcode_path, name, custom=True)
    return redirect(url_for("custom_barcodes"))


# -- Edit Item --

@app.route("/edit_item", methods=["POST"])
@login_required
def edit_item():
    original_name = request.form.get("original_name", "").strip()
    new_name      = request.form.get("name", "").strip()
    new_desc      = request.form.get("description", "").strip()
    new_barcode   = request.form.get("barcode", "").strip()

    if not original_name or not new_name or not new_barcode:
        return "Missing required fields", 400

    ensure_csv(ITEMS_CSV, CSV_COLUMNS)
    df = pd.read_csv(ITEMS_CSV, dtype=str).fillna("")

    mask = df["Item Name"].str.strip() == original_name
    if not mask.any():
        return "Item not found", 404

    df.loc[mask, "Item Name"]                          = new_name
    df.loc[mask, "Item Description / Alternate Names"] = new_desc
    df.loc[mask, "Barcode Number"]                     = new_barcode
    df.to_csv(ITEMS_CSV, index=False)

    # Regenerate label if barcode or name changed
    old_safe = sanitize_filename(original_name)
    new_safe = sanitize_filename(new_name)
    try:
        old_label   = os.path.join(LABEL_DIR, f"{old_safe}_label.png")
        old_barcode = os.path.join(BARCODE_DIR, f"{old_safe}.png")
        for f in [old_label, old_barcode]:
            if os.path.exists(f):
                os.remove(f)
        barcode_path = generate_barcode(new_barcode, new_name, custom=False)
        create_label(barcode_path, new_name, custom=False)
    except Exception:
        pass

    return redirect(url_for("index"))


# -- Delete Label --

@app.route("/delete_label", methods=["POST"])
@login_required
def delete_label():
    filepath  = request.form.get("filepath", "")
    page_type = request.form.get("page_type", "items")
    if not filepath:
        return "Missing filepath", 400

    try:
        os.remove(os.path.join("static", filepath))
    except FileNotFoundError:
        pass

    name      = os.path.splitext(os.path.basename(filepath))[0].replace("_label", "")
    safe_name = sanitize_filename(name)
    csv_path  = ITEMS_CSV   if page_type == "items" else CUSTOM_CSV
    png_dir   = BARCODE_DIR if page_type == "items" else CUSTOM_BARCODE_DIR

    try:
        os.remove(os.path.join(png_dir, f"{safe_name}.png"))
    except FileNotFoundError:
        pass

    df = pd.read_csv(csv_path)
    if page_type == "items":
        df = df[df["Item Name"].str.strip() != name]
    else:
        df = df[df["Name"].str.strip() != name]
    df.to_csv(csv_path, index=False)

    return redirect(url_for("index") if page_type == "items" else url_for("custom_barcodes"))


# -- Stock Check --

def _unwrap(data):
    # EJ API sometimes returns a list with one dict instead of a dict directly
    if isinstance(data, list):
        return data[0] if data else None
    return data

def _get_total_owned(item_id):
    # Use RentalInventory from Items/Details - this is the active owned count EJ UI shows.
    # Fallback: DeviceList with inactive exclusion set if Details doesn't have the field.
    try:
        details = _unwrap(ej.get_item_details(item_id))
        if details:
            total = details.get("RentalInventory")
            if total is not None:
                return int(total)
    except Exception:
        pass

    # Fallback: exclude known inactive @si barcodes from DeviceList.
    # Inactive set cross-referenced from EJ UI active vs show-inactive exports (2026-03-10).
    _inactive = {
        "@si94788", "@si94824", "@si94837", "@si94853", "@si94862",
        "@si94921", "@si94928", "@si94987", "@si94992", "@si94997",
        "@si95004", "@si95007", "@si95010", "@si95020", "@si95042",
        "@si95052", "@si95070", "@si95084", "@si95110", "@si95115",
        "@si95131", "@si95132", "@si95159", "@si95165", "@si95170",
    }
    try:
        devices = ej.get_device_list(item_id)
        if isinstance(devices, list) and devices:
            active = [d for d in devices if d.get("Barcode") not in _inactive]
            return len(active) if active else None
    except Exception:
        pass

    return None

def _parse_avail(avail_data, item_id, name="Unknown", total_owned=None):
    # Build normalised stock dict from EJ Items/Avail response.
    # Avail endpoint known response shapes:
    #   { "Inventory": 701, "CalcDay": "..." }        - available qty only (this EJ instance)
    #   { "Total": 10, "Booked": 3, "Avail": 7, ... } - full breakdown (newer EJ / WMS)
    avail_data = _unwrap(avail_data)
    if not avail_data:
        return None

    # ## Full breakdown format
    if "Total" in avail_data:
        total     = avail_data.get("Total",   0)
        booked    = avail_data.get("Booked",  0)
        service   = avail_data.get("Service", 0)
        avail_qty = avail_data.get("Avail",   total - booked - service)
        return {
            "name":      name,
            "item_id":   item_id,
            "total":     total,
            "warehouse": avail_qty,
            "on_jobs":   booked,
            "workshop":  None,    # service/workshop field not in this response
            "raw":       avail_data
        }

    # ## Inventory = available in warehouse; total comes from Items/Details
    if "Inventory" in avail_data:
        warehouse = avail_data.get("Inventory", 0)
        total     = total_owned                      # passed in from caller
        on_jobs   = (total - warehouse) if total is not None else None

        # Attach Items/Details response so we can find the correct total qty field
        item_details_raw = None
        try:
            item_details_raw = _unwrap(ej.get_item_details(item_id))
        except Exception:
            pass

        return {
            "name":             name,
            "item_id":          item_id,
            "total":            total,
            "warehouse":        warehouse,
            "on_jobs":          on_jobs,
            "workshop":         None,
            "raw":              avail_data,
            "item_details_raw": item_details_raw
        }

    # ## Unknown format - surface raw without crashing
    return {
        "name":      name,
        "item_id":   item_id,
        "total":     total_owned,
        "warehouse": None,
        "on_jobs":   None,
        "workshop":  None,
        "raw":       avail_data
    }

@app.route("/stock_check", methods=["GET", "POST"])
@login_required
def stock_check():
    result    = None    # single item result (barcode / item_id search)
    results   = None    # multiple item results (name search)
    error     = None
    query     = ""
    scan_type = "item_name"
    ej_ok     = ej_login()

    if request.method == "POST":
        scan_type = request.form.get("scan_type", "item_name")
        query     = request.form.get("query", "").strip()

        if not query:
            error = "Please enter a search term."
        elif not ej_ok:
            error = "EasyJob is not configured. Check your .env credentials."
        else:
            try:
                # ## Route query to the right lookup strategy
                #
                # Specific device barcode  →  BP2/205, @si94884, 94884
                # EJ item number           →  1007969.00
                # Plain integer            →  10934        (EJ internal item ID)
                # Everything else          →  name search  (wraps in wildcards automatically)
                #
                # All routes resolve to stock-type level - never a specific device.

                IS_SPECIFIC_BARCODE = re.match(r'^[A-Za-z0-9]+/\d+$', query)
                IS_SI_BARCODE       = re.match(r'^@?si\d+$', query, re.IGNORECASE)
                IS_BARE_SI          = re.match(r'^\d{5,6}$', query)
                IS_EJ_NUMBER        = re.match(r'^\d+\.\d+$', query)
                IS_EJ_ID            = re.match(r'^\d+$', query)

                if IS_SPECIFIC_BARCODE or IS_SI_BARCODE:
                    # Full device barcode - resolve to stock type via BarcodeSearch
                    device_info = ej.get_device_info(query)
                    if not device_info:
                        error = f"No device found for barcode '{query}'."
                    else:
                        device  = _unwrap(device_info)
                        item_id = (device.get("Additional") or {}).get("IdStockType") or device.get("IdStockType")
                        name    = device.get("Caption", query)
                        if not item_id:
                            error = f"Found device '{name}' but could not resolve stock type ID."
                        else:
                            avail       = ej.get_item_availability(item_id)
                            total_owned = _get_total_owned(item_id)
                            result      = _parse_avail(avail, item_id, name, total_owned)
                            if not result:
                                error = f"No availability data for '{name}'."

                elif IS_EJ_ID and not IS_EJ_NUMBER:
                    # Plain integer - try direct item ID first, fall back to @si barcode search.
                    # Can't distinguish 10934 (item ID) from 94884 (@si number) by pattern alone.
                    item_details = _unwrap(ej.get_item_details(int(query)))
                    if item_details and item_details.get("ID") or item_details and item_details.get("Id"):
                        name         = item_details.get("Caption", query)
                        total_owned  = _get_total_owned(int(query))
                        avail        = ej.get_item_availability(int(query))
                        result       = _parse_avail(avail, query, name, total_owned)
                        if not result:
                            error = f"No availability data for item ID {query}."
                    else:
                        # Not a valid item ID - try as bare @si number
                        device_info = ej.get_device_info(f"@si{query}")
                        if not device_info:
                            error = f"Nothing found for '{query}'. Try a name, barcode, or EJ item number."
                        else:
                            device  = _unwrap(device_info)
                            item_id = (device.get("Additional") or {}).get("IdStockType") or device.get("IdStockType")
                            name    = device.get("Caption", query)
                            if not item_id:
                                error = f"Found device '{name}' but could not resolve stock type ID."
                            else:
                                avail       = ej.get_item_availability(item_id)
                                total_owned = _get_total_owned(item_id)
                                result      = _parse_avail(avail, item_id, name, total_owned)
                                if not result:
                                    error = f"No availability data for '{name}'."

                else:
                    # Name, base barcode (BP2, BP2/), EJ number (1007969.00), or any text
                    # Strip trailing slash, wrap in wildcards so partial names match
                    search_term = f"*{query.rstrip('/')}*"
                    items_found = ej.get_all_items(searchtext=search_term)
                    if not items_found:
                        error = f"No items found matching '{query}'."
                    else:
                        results = []
                        for item in items_found:
                            item_id = item.get("Id") or item.get("ID") or item.get("IdStockType")
                            name    = item.get("Caption", str(item_id))
                            if not item_id:
                                continue
                            try:
                                total_owned = _get_total_owned(item_id)
                                avail       = ej.get_item_availability(item_id)
                                parsed      = _parse_avail(avail, item_id, name, total_owned)
                                if parsed:
                                    results.append(parsed)
                            except Exception as e:
                                error = f"Error fetching availability for '{name}': {e}"

                        if not results and not error:
                            error = f"No items found matching '{query}'."

            except RuntimeError as e:
                error = str(e)
            except Exception as e:
                error = f"Unexpected error: {e}"

    return render_template(
        "stock_check.html",
        result=result,
        results=results,
        error=error,
        query=query,
        scan_type=scan_type,
        ej_ok=ej_ok,
        page="stock_check"
    )



# -- Job Watching --

def load_watchers(username=None, show_all=False):
    # Returns all watchers from disk, optionally filtered by owner.
    # show_all=True (admin toggle) returns everyone's watchers.
    if not os.path.exists(WATCHERS_FILE):
        return []
    try:
        with open(WATCHERS_FILE, "r") as f:
            all_w = json.load(f)
    except Exception:
        return []
    if show_all or not username:
        return all_w
    return [w for w in all_w if w.get("owner") == username]

def load_all_watchers():
    # Always returns the full list regardless of user - used for save operations.
    if not os.path.exists(WATCHERS_FILE):
        return []
    try:
        with open(WATCHERS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_watchers(watchers):
    with open(WATCHERS_FILE, "w") as f:
        json.dump(watchers, f, indent=2)

CALENDAR_FILE = "./calendar_watch.json"

def _empty_calendar():
    return {"entries": {}, "last_checked": None, "new_entries": [], "errors": []}

def _load_raw_calendar():
    # Load the raw file - entries and new_entries are both keyed by username.
    if not os.path.exists(CALENDAR_FILE):
        return {"entries_by_user": {}, "new_entries_by_user": {}, "last_checked_by_user": {}, "errors_by_user": {}}
    try:
        with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {"entries_by_user": {}, "new_entries_by_user": {}, "last_checked_by_user": {}, "errors_by_user": {}}

def load_calendar_watch(username=None):
    # Returns a view of the calendar data for the given user.
    # All data is per-user - entries, new_entries, last_checked, errors.
    raw = _load_raw_calendar()
    if username:
        return {
            "entries":      raw.get("entries_by_user",      {}).get(username, {}),
            "new_entries":  raw.get("new_entries_by_user",  {}).get(username, []),
            "last_checked": raw.get("last_checked_by_user", {}).get(username),
            "errors":       raw.get("errors_by_user",       {}).get(username, []),
        }
    return _empty_calendar()

def save_calendar_watch(data, username=None, new_entries_for_user=None):
    # Saves a user's calendar slice back into the shared file.
    # data must be a user-view dict (as returned by load_calendar_watch).
    raw = _load_raw_calendar()
    if username:
        raw.setdefault("entries_by_user",      {})[username] = data.get("entries", {})
        raw.setdefault("last_checked_by_user", {})[username] = data.get("last_checked")
        raw.setdefault("errors_by_user",       {})[username] = data.get("errors", [])
        if new_entries_for_user is not None:
            raw.setdefault("new_entries_by_user", {})[username] = new_entries_for_user
        else:
            raw.setdefault("new_entries_by_user", {})[username] = data.get("new_entries", [])
    with open(CALENDAR_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)

def _format_ej_date(raw: str) -> str:
    # EJ dates look like "2026-03-16T09:00:00.0000000" - strip to first 19 chars to ignore fractional seconds
    if not raw:
        return ""
    try:
        dt = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
        if dt.hour == 0 and dt.minute == 0:
            return dt.strftime("%d %b %Y")       # e.g. "16 Mar 2026"
        return dt.strftime("%d %b, %H:%M")       # e.g. "16 Mar, 09:00"
    except ValueError:
        pass
    try:
        dt = datetime.strptime(raw[:10], "%Y-%m-%d")
        return dt.strftime("%d %b %Y")
    except ValueError:
        return raw

def _parse_caption(caption: str):
    # "Prep | Trainee Prep"  →  type="Prep",     role="Trainee Prep"
    # "LED | LED Engineer"   →  type="LED",      role="LED Engineer"
    # "Edays - External"     →  type="Edays - External", role=None
    if "|" in caption:
        parts = [p.strip() for p in caption.split("|", 1)]
        return parts[0], parts[1]
    return caption.strip(), None

def _entry_key(entry):
    return str(entry.get("Id") or f"{entry.get('Caption','')}|{entry.get('StartDate','')}")

def _entry_summary(entry):
    caption   = (entry.get("Caption")     or "").strip()
    post      = (entry.get("PostCaption") or "").strip()
    raw_start = entry.get("StartDate") or ""
    raw_end   = entry.get("EndDate")   or ""

    job_type, role = _parse_caption(caption)

    # Use PostCaption as the title only if it looks like a real job name
    # (contains a space or is long enough to be meaningful - not just "Approved" etc.)
    use_post = post and (len(post) > 12 or " " in post)
    title    = post if use_post else caption

    return {
        "id":        _entry_key(entry),
        "title":     title,
        "type":      job_type,
        "role":      role,
        "color":     entry.get("Color") or "",
        "start":     _format_ej_date(raw_start),
        "end":       _format_ej_date(raw_end),
        "start_raw": raw_start,
    }

def refresh_calendar_watch(app_username=None, ej_username=None, ej_password=None):
    # Fetches 14 days of calendar data for the triggering user only.
    # All data (entries, new_entries, last_checked, errors) saved to that user's slice.
    data = load_calendar_watch(username=app_username)
    if not ej_username or not ej_password:
        data["errors"] = ["No EasyJob credentials configured for this account."]
        save_calendar_watch(data, username=app_username)
        return
    try:
        ej.quick_login(username=ej_username, password=ej_password)
    except Exception as e:
        data["errors"] = [f"EasyJob login failed: {e}"]
        save_calendar_watch(data, username=app_username)
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    try:
        raw = ej.get_calendar(start_date=today_str, days=14)
    except Exception as e:
        data["errors"]       = [str(e)]
        data["last_checked"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        save_calendar_watch(data, username=app_username)
        return

    if not isinstance(raw, list):
        data["errors"]       = [f"Unexpected response: {type(raw).__name__}"]
        data["last_checked"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        save_calendar_watch(data, username=app_username)
        return

    known    = {}
    new_ones = []
    today    = datetime.now().date()
    old_keys = set(data.get("entries", {}).keys())

    for entry in raw:
        caption = (entry.get("Caption") or "").lower()
        if not ("prep" in caption or "on site" in caption or "onsite" in caption):
            continue

        raw_end = (entry.get("EndDate") or entry.get("StartDate") or "")[:10]
        try:
            if datetime.strptime(raw_end, "%Y-%m-%d").date() < today:
                continue
        except ValueError:
            pass

        key     = _entry_key(entry)
        summary = _entry_summary(entry)
        if key not in old_keys:
            new_ones.append(summary)
        known[key] = summary

    # Merge new unseen entries - keep existing unseen ones that aren't being replaced
    existing_new = data.get("new_entries", [])
    new_ids      = {n["id"] for n in new_ones}
    merged_new   = new_ones + [e for e in existing_new if e["id"] not in new_ids]

    data["entries"]      = known
    data["new_entries"]  = merged_new[:50]
    data["last_checked"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    data["errors"]       = []

    save_calendar_watch(data, username=app_username)


@app.route("/calendar_watch/refresh", methods=["POST"])
@login_required
def calendar_watch_refresh():
    app_user = session.get("username", "")
    ej_user  = session.get("ej_username", "")
    ej_pass  = session.get("ej_password", "")
    threading.Thread(target=refresh_calendar_watch, args=(app_user, ej_user, ej_pass), daemon=True).start()
    return jsonify({"started": True})

@app.route("/calendar_watch/status", methods=["GET"])
@login_required
def calendar_watch_status():
    return jsonify(load_calendar_watch(username=session.get("username")))

@app.route("/calendar_watch/dismiss", methods=["POST"])
@login_required
def calendar_watch_dismiss():
    entry_id = request.form.get("entry_id", "").strip()
    username = session.get("username")
    data     = load_calendar_watch(username=username)
    new_entries = [e for e in data.get("new_entries", []) if e["id"] != entry_id]
    save_calendar_watch(data, username=username, new_entries_for_user=new_entries)
    return jsonify({"ok": True})

@app.route("/calendar_watch/dismiss_all", methods=["POST"])
@login_required
def calendar_watch_dismiss_all():
    username = session.get("username")
    data     = load_calendar_watch(username=username)
    save_calendar_watch(data, username=username, new_entries_for_user=[])
    return jsonify({"ok": True})


@app.route("/polling")
@login_required
def polling():
    username  = session.get("username")
    is_admin  = session.get("role") == "admin"
    show_all  = is_admin and request.args.get("show_all") == "1"
    watchers  = load_watchers(username=username, show_all=show_all)
    ej_ok     = ej_login()
    return render_template("polling.html", watchers=watchers, ej_ok=ej_ok,
                           page="job_watching", show_all=show_all, is_admin=is_admin)

def _shipping_status(day_time_out, day_time_in, returned=False):
    # Derive shipping status from DayTimeOut / DayTimeIn.
    # "returned" is a manual flag set by staff via the UI.
    #
    #   Upcoming          - before DayTimeOut
    #   Shipped           - past DayTimeOut, before DayTimeIn
    #   Past Return Date  - past DayTimeIn, not manually marked returned
    #   Returned          - manually marked returned by staff
    if returned:
        return "Returned"
    if not day_time_out:
        return None
    try:
        now      = datetime.now()
        time_out = datetime.strptime(day_time_out[:19], "%Y-%m-%dT%H:%M:%S")
        time_in  = datetime.strptime(day_time_in[:19],  "%Y-%m-%dT%H:%M:%S") if day_time_in else None

        if now < time_out:
            return "Upcoming"
        if time_in is None or now < time_in:
            return "Shipped"
        return "Past Return Date"
    except (ValueError, TypeError):
        return None

def _fetch_watcher_details(job_id, job_no):
    # Fetch job details + items for a watcher entry.
    # Returns (job_state_str, day_time_out, day_time_in, items_dict, error_str)
    try:
        details = ej.get_job_details(int(job_id))
        if not details:
            return None, None, None, {}, "Job details not found"

        # JobState can be a dict {"Caption": "Confirmed"} or a plain string depending on EJ version
        job_state_raw = details.get("JobState", "Unknown")
        if isinstance(job_state_raw, dict):
            job_state = job_state_raw.get("Caption", "Unknown")
        else:
            job_state = str(job_state_raw)

        day_time_out = details.get("DayTimeOut") or ""
        day_time_in  = details.get("DayTimeIn")  or ""

        items_dict = {}
        try:
            items = ej.get_items_in_job(job_id)
            if items:
                items_dict = {
                    str(iid): {"name": i.get("name"), "qty": i.get("quantity")}
                    for iid, i in items.items()
                }
        except Exception:
            pass

        return job_state, day_time_out, day_time_in, items_dict, None

    except Exception as e:
        return None, None, None, {}, str(e)


@app.route("/polling/add", methods=["POST"])
@login_required
def polling_add():
    job_no = request.form.get("job_no", "").strip()
    label  = request.form.get("label",  "").strip()
    if not job_no:
        return redirect(url_for("polling"))

    username = session.get("username")
    all_watchers = load_all_watchers()
    # Prevent duplicate per user (same job_no + same owner)
    if any(w["job_no"] == job_no and w.get("owner") == username for w in all_watchers):
        return redirect(url_for("polling"))

    watcher = {
        "job_no":            job_no,
        "label":             label or job_no,
        "owner":             username,
        "added":             datetime.now().strftime("%Y-%m-%d %H:%M"),
        "last_status":       None,
        "last_locked":       None,
        "shipping_status":   None,
        "day_time_out":      None,
        "day_time_in":       None,
        "last_items":        {},
        "last_changed":      None,
        "has_change":        False,
        "returned":          False,
        "error":             None
    }

    try:
        ej_login()
        job_info = ej.get_job_info(job_no)
        if job_info:
            job_data = job_info[0]
            job_id   = job_data.get("Id")
            watcher["label"] = label or job_data.get("Caption", job_no)

            job_state, day_time_out, day_time_in, items_dict, err = _fetch_watcher_details(job_id, job_no)
            watcher["last_status"]     = job_state
            watcher["last_locked"]     = (job_state == "Proposed") if job_state else None
            watcher["day_time_out"]    = day_time_out
            watcher["day_time_in"]     = day_time_in
            watcher["shipping_status"] = _shipping_status(day_time_out, day_time_in, returned=False)
            watcher["last_items"]      = items_dict
            if err:
                watcher["error"] = err
    except Exception as e:
        watcher["error"] = str(e)

    all_watchers.append(watcher)
    save_watchers(all_watchers)
    return redirect(url_for("polling"))

@app.route("/polling/mark_returned", methods=["POST"])
@login_required
def polling_mark_returned():
    job_no   = request.form.get("job_no", "").strip()
    undo     = request.form.get("undo", "0") == "1"
    username = session.get("username")
    watchers = load_all_watchers()
    for w in watchers:
        if w["job_no"] == job_no and w.get("owner") == username:
            w["returned"]          = not undo
            w["shipping_status"]   = _shipping_status(
                w.get("day_time_out"), w.get("day_time_in"), returned=not undo
            )
    save_watchers(watchers)
    return redirect(url_for("polling"))

@app.route("/polling/remove", methods=["POST"])
@login_required
def polling_remove():
    job_no   = request.form.get("job_no", "").strip()
    username = session.get("username")
    watchers = [w for w in load_all_watchers()
                if not (w["job_no"] == job_no and w.get("owner") == username)]
    save_watchers(watchers)
    return redirect(url_for("polling"))

@app.route("/polling/clear_flag", methods=["POST"])
@login_required
def polling_clear_flag():
    job_no   = request.form.get("job_no", "").strip()
    username = session.get("username")
    watchers = load_all_watchers()

    target = next((w for w in watchers
                   if w["job_no"] == job_no and w.get("owner") == username), None)
    # If acknowledging "Past Return Date", auto-delete the watcher
    if target and target.get("shipping_status") == "Past Return Date":
        watchers = [w for w in watchers
                    if not (w["job_no"] == job_no and w.get("owner") == username)]
    elif target:
        target["has_change"] = False

    save_watchers(watchers)
    return redirect(url_for("polling"))

@app.route("/polling/refresh", methods=["POST"])
@login_required
def polling_refresh():
    username     = session.get("username")
    all_watchers = load_all_watchers()
    mine         = [w for w in all_watchers if w.get("owner") == username]
    if not ej_login():
        return redirect(url_for("polling"))

    for w in mine:
        try:
            job_info = ej.get_job_info(w["job_no"])
            if not job_info:
                w["error"] = "Job not found"
                continue

            job_id = job_info[0].get("Id")
            job_state, day_time_out, day_time_in, new_items, err = _fetch_watcher_details(job_id, w["job_no"])

            new_shipping = _shipping_status(day_time_out, day_time_in, returned=w.get("returned", False))
            new_locked   = (job_state == "Proposed") if job_state else None

            status_changed   = w.get("last_status")     != job_state
            locked_changed   = w.get("last_locked")     != new_locked
            shipping_changed = w.get("shipping_status") != new_shipping
            items_changed    = w.get("last_items", {})  != new_items

            if status_changed or locked_changed or shipping_changed or items_changed:
                w["has_change"]   = True
                w["last_changed"] = datetime.now().strftime("%Y-%m-%d %H:%M")

            w["last_status"]     = job_state
            w["last_locked"]     = new_locked
            w["shipping_status"] = new_shipping
            w["day_time_out"]    = day_time_out
            w["day_time_in"]     = day_time_in
            w["last_items"]      = new_items
            w["error"]           = err

        except Exception as e:
            w["error"] = str(e)

    # Merge refreshed entries back into the full list
    mine_nos = {w["job_no"] for w in mine}
    others   = [w for w in all_watchers if w.get("owner") != username]
    save_watchers(others + mine)
    return redirect(url_for("polling"))




# -- EJ Item Sync --

SYNC_STATUS_FILE = "./sync_status.json"

def load_sync_status():
    if not os.path.exists(SYNC_STATUS_FILE):
        return {"last_sync": None, "added": 0, "skipped": 0, "errors": []}
    with open(SYNC_STATUS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_sync_status(status):
    with open(SYNC_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)

def sync_ej_items(ej_username=None, ej_password=None):
    # Pull full item list from EJ and merge into items.csv.
    #
    # Items WITH devices (individually barcoded):
    #   → Added to CSV with name + description only, no barcode/label.
    #   → Barcode is managed per-device via RP barcodes; no generic label needed.
    #
    # Items WITHOUT devices (non-barcoded / consumable stock):
    #   → Added to CSV with EJ item number as barcode, label auto-generated.
    #
    # Existing entries are never overwritten - sync only adds missing items.

    result = {"running": True, "added": 0, "skipped": 0, "total": 0, "processed": 0, "errors": [], "last_sync": None}
    save_sync_status(result)

    def _finish(r):
        r["running"]    = False
        r["last_sync"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
        save_sync_status(r)
        return r

    if not ej_username or not ej_password:
        result["errors"].append("No EasyJob credentials configured for this account.")
        return _finish(result)
    try:
        ej.quick_login(username=ej_username, password=ej_password)
    except Exception as e:
        result["errors"].append(f"EasyJob login failed: {e}")
        return _finish(result)

    try:
        ej_items = ej.get_all_items_full()
    except Exception as e:
        result["errors"].append(f"Failed to fetch items from EJ: {e}")
        return _finish(result)

    if not isinstance(ej_items, list):
        result["errors"].append(f"Unexpected response type from EJ: {type(ej_items).__name__}")
        return _finish(result)

    result["total"] = len(ej_items)
    save_sync_status(result)

    ensure_csv(ITEMS_CSV, CSV_COLUMNS)
    df = pd.read_csv(ITEMS_CSV, dtype=str).fillna("")
    existing_names = set(df["Item Name"].str.strip().str.lower())

    new_rows = []
    for item in ej_items:
        result["processed"] += 1

        name = (item.get("Caption") or "").strip()
        if not name:
            continue
        if name.lower() in existing_names:
            result["skipped"] += 1
            continue

        desc        = (item.get("Category") or "").strip()
        ej_number   = (item.get("Number") or "").strip()
        has_devices = bool(item.get("HasDevices") or item.get("Barcoded") or item.get("DeviceCount"))
        item_id     = item.get("Id") or item.get("ID") or item.get("IdStockType")

        if has_devices:
            # Individually barcoded - no generic barcode/label
            new_rows.append([name, desc, "", "", ""])
        else:
            # Non-barcoded - use EJ item number as barcode and auto-generate label
            barcode = ej_number or str(item_id or "")
            if not barcode:
                new_rows.append([name, desc, "", "", ""])
            else:
                try:
                    barcode_path = generate_barcode(barcode, name, custom=False)
                    create_label(barcode_path, name, custom=False)
                    new_rows.append([name, desc, barcode, "", ""])
                except Exception as e:
                    result["errors"].append(f"Label gen failed for '{name}': {e}")
                    new_rows.append([name, desc, barcode, "", ""])

        existing_names.add(name.lower())
        result["added"] += 1

        # Write progress to disk every 25 items so the UI can poll it
        if result["added"] % 25 == 0:
            save_sync_status(result)

    if new_rows:
        with open(ITEMS_CSV, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(new_rows)

    return _finish(result)


@app.route("/sync_items", methods=["POST"])
@admin_required
def sync_items_route():
    status = load_sync_status()
    if status.get("running"):
        return jsonify({"already_running": True})
    # Mark as running immediately so the UI knows
    status["running"] = True
    status["last_sync"] = None
    save_sync_status(status)
    ej_user = session.get("ej_username", "")
    ej_pass = session.get("ej_password", "")
    threading.Thread(target=sync_ej_items, args=(ej_user, ej_pass), daemon=True).start()
    return jsonify({"started": True})


@app.route("/sync_status", methods=["GET"])
@login_required
def sync_status_route():
    return jsonify(load_sync_status())



# -- One-time JSON Import --

IMPORT_STATUS_FILE = "./import_status.json"

def load_import_status():
    if not os.path.exists(IMPORT_STATUS_FILE):
        return None
    with open(IMPORT_STATUS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_import_status(status):
    with open(IMPORT_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)

def run_import(items):
    # Background worker for the one-time JSON import.
    #
    # For each item:
    #   - Calls DeviceList to check if individually barcoded
    #   - Barcoded  → CSV entry with no barcode/label
    #   - Non-barcoded → CSV entry + generate barcode + generate label
    #
    # Progress is written to import_status.json so the UI can poll it.

    total  = len(items)
    status = {
        "running":    True,
        "total":      total,
        "processed":  0,
        "added":      0,
        "skipped":    0,
        "barcoded":   0,
        "unbarcoded": 0,
        "errors":     [],
        "done_at":    None,
    }
    save_import_status(status)

    ensure_csv(ITEMS_CSV, CSV_COLUMNS)
    df             = pd.read_csv(ITEMS_CSV, dtype=str).fillna("")
    existing_names = set(df["Item Name"].str.strip().str.lower())
    new_rows       = []

    for item in items:
        name       = (item.get("Caption") or "").strip()

        # Skip items belonging to other regions/subsidiaries
        if re.match(r'^<(AUS|SUB|ES|USA|FR|DE|IT|NL|AU)\>', name, re.IGNORECASE):
            status["skipped"] += 1
            if status["processed"] % 25 == 0:
                save_import_status(status)
            continue
        number     = (item.get("Number") or "").strip()  # kept for reference, not used in CSV
        category   = (item.get("Category") or "").strip()
        cat_parent = (item.get("CategoryParent") or "").strip()
        item_id    = item.get("IdStockType")
        desc       = f"{cat_parent} / {category}".strip(" /")

        status["processed"] += 1

        if not name or not item_id:
            status["processed"] += 1
            save_import_status(status)
            continue

        if name.lower() in existing_names:
            status["skipped"] += 1
            # Still save progress periodically
            if status["processed"] % 25 == 0:
                save_import_status(status)
            continue

        # Check DeviceList - item is individually barcoded only if devices have InventoryNumber values
        has_devices = False
        try:
            devices     = ej.get_device_list(item_id)
            has_devices = isinstance(devices, list) and any(
                d.get("InventoryNumber") for d in devices
            )
        except Exception as e:
            status["errors"].append(f"DeviceList failed for '{name}' (id {item_id}): {e}")

        if has_devices:
            # Individually barcoded (has InventoryNumber like BP2/001) - name + desc only, no barcode/label
            new_rows.append([name, desc, "", "", ""])
            status["barcoded"] += 1
        else:
            # Non-barcoded stock - no barcode, no label
            new_rows.append([name, desc, "", "", ""])
            status["unbarcoded"] += 1

        existing_names.add(name.lower())
        status["added"] += 1

        if status["processed"] % 10 == 0:
            save_import_status(status)

    # Flush all new rows at once
    if new_rows:
        with open(ITEMS_CSV, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(new_rows)

    status["running"] = False
    status["done_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_import_status(status)


@app.route("/import", methods=["GET"])
@admin_required
def import_page():
    status       = load_import_status()
    fetch_status = load_fetch_status()
    return render_template("import.html", page="import", status=status, fetch_running=fetch_status.get("running", False))


FETCH_STATUS_FILE = "./fetch_status.json"
EJ_EXPORT_FILE    = "./ej_export.json"

# fetch_status.json - metadata only; items live in ej_export.json to avoid huge in-memory JSON
def load_fetch_status():
    if not os.path.exists(FETCH_STATUS_FILE):
        return {"running": False}
    try:
        with open(FETCH_STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {"running": False}  # empty or corrupt file - treat as fresh

def save_fetch_status(status):
    with open(FETCH_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)

def load_ej_export():
    if not os.path.exists(EJ_EXPORT_FILE):
        return []
    with open(EJ_EXPORT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _run_fetch(ej_username=None, ej_password=None):
    save_fetch_status({"running": True, "count": 0, "error": None})
    if not ej_username or not ej_password:
        save_fetch_status({"running": False, "count": 0, "error": "No EasyJob credentials configured for this account."})
        return
    try:
        ej.quick_login(username=ej_username, password=ej_password)
        items = ej.get_all_items_full()
        if not isinstance(items, list):
            save_fetch_status({"running": False, "count": 0, "error": f"Unexpected response: {type(items).__name__}"})
            return
        with open(EJ_EXPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
        save_fetch_status({"running": False, "count": len(items), "error": None})
    except Exception as e:
        save_fetch_status({"running": False, "count": 0, "error": str(e)})


@app.route("/import/fetch_from_ej", methods=["POST"])
@admin_required
def import_fetch_from_ej():
    status = load_fetch_status()
    if status.get("running"):
        return jsonify({"already_running": True})
    ej_user = session.get("ej_username", "")
    ej_pass = session.get("ej_password", "")
    threading.Thread(target=_run_fetch, args=(ej_user, ej_pass), daemon=True).start()
    return jsonify({"started": True})


@app.route("/import/fetch_status", methods=["GET"])
@admin_required
def import_fetch_status():
    return jsonify(load_fetch_status())


@app.route("/import/start", methods=["POST"])
@admin_required
def import_start():
    if load_import_status() and load_import_status().get("running"):
        return jsonify({"error": "Import already running"}), 409

    # Read items from ej_export.json on disk - no POST body needed
    fetch = load_fetch_status()
    if fetch.get("error"):
        return jsonify({"error": f"Fetch error: {fetch['error']}"}), 400
    if fetch.get("running"):
        return jsonify({"error": "Fetch still in progress - wait for it to finish"}), 409

    items = load_ej_export()
    if not items:
        return jsonify({"error": "No items found - run Fetch from EasyJob first"}), 400

    if not ej_login():
        return jsonify({"error": "EasyJob not configured - check .env credentials"}), 500

    threading.Thread(target=run_import, args=(items,), daemon=True).start()
    return jsonify({"started": True, "total": len(items)})


@app.route("/import/status", methods=["GET"])
@admin_required
def import_status():
    status = load_import_status()
    if not status:
        return jsonify({"running": False, "never_run": True})
    return jsonify(status)


# -- Login / Logout --

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("username"):
        return redirect(url_for("index"))
    error    = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        users    = load_users()
        user     = users.get(username)
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["username"]     = username
            session["display_name"] = user.get("display_name", username)
            session["role"]         = user.get("role", "user")
            session["ej_username"]  = user.get("ej_username", "")
            session["ej_password"]  = decrypt_field(user.get("ej_password", ""))
            ej.TOKEN = None
            return redirect(url_for("index"))
        error = "Invalid username or password."
    return render_template("login.html", error=error, username=username)

@app.route("/logout")
def logout():
    ej.TOKEN = None
    session.clear()  # clears ej_token along with everything else
    return redirect(url_for("login"))


# -- Admin: User Management --

@app.route("/admin/users")
@admin_required
def admin_users():
    users   = load_users()
    message = request.args.get("message")
    msg_type = request.args.get("msg_type", "success")
    return render_template("admin_users.html", users=users,
                           message=message, message_type=msg_type, page="admin_users")

@app.route("/admin/users/add", methods=["POST"])
@admin_required
def admin_add_user():
    username     = request.form.get("username", "").strip().lower()
    display_name = request.form.get("display_name", "").strip()
    password     = request.form.get("password", "")
    role         = request.form.get("role", "user")
    ej_username  = request.form.get("ej_username", "").strip()
    ej_password  = request.form.get("ej_password", "")

    if not username or not password:
        return redirect(url_for("admin_users", message="Username and password are required.", msg_type="danger"))

    users = load_users()
    if username in users:
        return redirect(url_for("admin_users", message=f"User '{username}' already exists.", msg_type="danger"))

    users[username] = {
        "password_hash": generate_password_hash(password),
        "role":          role,
        "display_name":  display_name or username,
        "ej_username":   ej_username,
        "ej_password":   encrypt_field(ej_password),
    }
    save_users(users)
    return redirect(url_for("admin_users", message=f"User '{username}' created."))

@app.route("/admin/users/edit", methods=["POST"])
@admin_required
def admin_edit_user():
    username     = request.form.get("username", "").strip().lower()
    display_name = request.form.get("display_name", "").strip()
    password     = request.form.get("password", "")
    role         = request.form.get("role", "user")
    ej_username  = request.form.get("ej_username", "").strip()
    ej_password  = request.form.get("ej_password", "")

    users = load_users()
    if username not in users:
        return redirect(url_for("admin_users", message="User not found.", msg_type="danger"))

    users[username]["role"]         = role
    users[username]["display_name"] = display_name or username
    users[username]["ej_username"]  = ej_username
    if password:
        users[username]["password_hash"] = generate_password_hash(password)
    if ej_password:
        users[username]["ej_password"] = encrypt_field(ej_password)

    save_users(users)

    # If editing the currently logged-in user, refresh their session data
    if username == session.get("username"):
        session["display_name"] = users[username]["display_name"]
        session["role"]         = users[username]["role"]
        session["ej_username"]  = users[username]["ej_username"]
        if ej_password:
            session["ej_password"] = ej_password  # plaintext - user just typed it

    return redirect(url_for("admin_users", message=f"User '{username}' updated."))

@app.route("/admin/users/delete", methods=["POST"])
@admin_required
def admin_delete_user():
    username = request.form.get("username", "").strip().lower()
    if username == session.get("username"):
        return redirect(url_for("admin_users", message="You can't delete your own account.", msg_type="danger"))
    users = load_users()
    if username in users:
        del users[username]
        save_users(users)
    return redirect(url_for("admin_users", message=f"User '{username}' deleted."))


# -- 403 page --

@app.route("/403")
def forbidden():
    return render_template("403.html", page=None), 403


# -- Barcode Scanner --

@app.route("/barcode_finder")
@login_required
def barcode_finder():
    return render_template("barcode_finder.html", page="barcode_finder")


# -- Run --

if __name__ == "__main__":
    ensure_csv(ITEMS_CSV, CSV_COLUMNS)
    ensure_csv(CUSTOM_CSV, CUSTOM_COLUMNS)
    app.run(debug=True, host="0.0.0.0")
