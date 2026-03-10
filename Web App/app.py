import sys
import os
import csv
import re
import json
import requests
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for
from PIL import Image, ImageDraw, ImageFont

# Add parent directory to path to import API module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from API import easyjob as ej

app = Flask(__name__)


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

# Label config
LABEL_WIDTH_MM       = 50
LABEL_HEIGHT_MM      = 25
DPI                  = 300
TEXT_HEIGHT_FRACTION = 1 / 3
PADDING_MM           = 0.5

for d in [BARCODE_DIR, LABEL_DIR, CUSTOM_BARCODE_DIR, CUSTOM_LABEL_DIR]:
    os.makedirs(d, exist_ok=True)


# -- Utils --

def mm_to_px(mm):
    return int((mm / 25.4) * DPI)

LABEL_WIDTH  = mm_to_px(LABEL_WIDTH_MM)
LABEL_HEIGHT = mm_to_px(LABEL_HEIGHT_MM)
PADDING      = mm_to_px(PADDING_MM)
TEXT_HEIGHT  = int(LABEL_HEIGHT * TEXT_HEIGHT_FRACTION)

def sanitize_filename(name):
    return re.sub(r'[\\/:*?"<>| ]+', '_', name).strip()

def ensure_csv(path, columns):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(columns)

def ej_login() -> bool:
    # Attempt EasyJob login, return True if successful
    try:
        if not ej.TOKEN:
            ej.quick_login()
        return True
    except Exception:
        return False


# -- Load Items --

def wildcard_to_regex(query):
    return re.escape(query).replace("\\*", ".*")

def load_items(query=""):
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

    items = []
    for _, row in df.iterrows():
        name = row["Item Name"]
        if not name:
            continue
        safe = sanitize_filename(name)
        items.append({
            "name":        name,
            "description": row["Item Description / Alternate Names"],
            "barcode":     row["Barcode Number"],
            "label":       f"labels/{safe}_label.png"
        })
    return items

def load_custom_barcodes(query=""):
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

def generate_barcode(barcode, name, custom=False):
    safe     = sanitize_filename(name)
    dir_path = CUSTOM_BARCODE_DIR if custom else BARCODE_DIR
    path     = os.path.join(dir_path, f"{safe}.png")
    r = requests.get(BARCODE_API.format(barcode), timeout=10)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    return path

def create_label(barcode_img_path, name, custom=False):
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
def index():
    query = request.form.get("search", "").strip() if request.method == "POST" else ""
    items = load_items(query)
    return render_template("index.html", items=items, query=query, page="items")

@app.route("/add", methods=["POST"])
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


# -- Delete Label --

@app.route("/delete_label", methods=["POST"])
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

def _get_total_from_details(item_id):
    # Try Items/Details for a qty field first.
    # Fallback: count DeviceList by unique InventoryNumber.
    #
    # Why unique InventoryNumber?
    # - EJ API DeviceList returns ALL records including inactive ones (no active/inactive flag).
    # - Inactive devices are replacement units: the old @si record is deactivated but kept,
    #   and a new @si record is created with the same InventoryNumber (e.g. BP2/001).
    # - Active devices that haven't been replaced have exactly one @si per InventoryNumber.
    # - Deduplicating by InventoryNumber therefore gives the correct active count (773).
    details = _unwrap(ej.get_item_details(item_id))
    if details:
        total = (
            details.get("Qty") or
            details.get("StockQty") or
            details.get("QuantityTotal") or
            details.get("Quantity")
        )
        if total is not None:
            return total

    try:
        devices = ej.get_device_list(item_id)
        if isinstance(devices, list):
            unique = len({d.get("InventoryNumber") for d in devices if d.get("InventoryNumber")})
            return unique if unique else len(devices)
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

    # ## Unknown format — surface raw without crashing
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
                # ## Search by RP barcode (e.g. BP2/205)
                if scan_type == "barcode":
                    device_info = ej.get_device_info(query)
                    if not device_info:
                        error = f"No device found for barcode: {query}"
                    else:
                        # BarcodeSearch may return a list or single dict — unwrap either
                        device  = _unwrap(device_info)
                        item_id = (device.get("Additional") or {}).get("IdStockType") or device.get("IdStockType")
                        name    = device.get("Caption", query)
                        if not item_id:
                            error = f"Found device '{name}' but could not resolve Item ID."
                        else:
                            avail       = ej.get_item_availability(item_id)
                            total_owned = _get_total_from_details(item_id)
                            result      = _parse_avail(avail, item_id, name, total_owned)
                            if not result:
                                error = f"No availability data for item ID {item_id}."

                # ## Search by numeric Item ID
                elif scan_type == "item_id":
                    item_details = _unwrap(ej.get_item_details(int(query)))
                    name        = item_details.get("Caption", query) if item_details else query
                    total_owned = _get_total_from_details(int(query))
                    avail       = ej.get_item_availability(int(query))
                    result      = _parse_avail(avail, query, name, total_owned)
                    if not result:
                        error = f"No availability data for item ID {query}."

                # ## Search by item name — may return multiple items
                elif scan_type == "item_name":
                    items_found = ej.get_all_items(searchtext=query)
                    if not items_found:
                        error = f"No items found matching '{query}'."
                    else:
                        results = []
                        for item in items_found:
                            item_id = item.get("Id")
                            name    = item.get("Caption", str(item_id))
                            if not item_id:
                                continue
                            try:
                                total_owned = item.get("Qty") or item.get("StockQty") or item.get("QuantityTotal")
                                avail       = ej.get_item_availability(item_id)
                                parsed      = _parse_avail(avail, item_id, name, total_owned)
                                if parsed:
                                    results.append(parsed)
                            except Exception:
                                pass    # skip items that fail availability lookup

                        if not results:
                            error = f"Found items matching '{query}' but could not retrieve availability."

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


# -- Polling / Job Watcher --

def load_watchers():
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

@app.route("/polling")
def polling():
    watchers = load_watchers()
    ej_ok    = ej_login()
    return render_template("polling.html", watchers=watchers, ej_ok=ej_ok, page="polling")

@app.route("/polling/add", methods=["POST"])
def polling_add():
    job_no = request.form.get("job_no", "").strip()
    label  = request.form.get("label",  "").strip()
    if not job_no:
        return redirect(url_for("polling"))

    watchers = load_watchers()
    if any(w["job_no"] == job_no for w in watchers):
        return redirect(url_for("polling"))

    watcher = {
        "job_no":       job_no,
        "label":        label or job_no,
        "added":        datetime.now().strftime("%Y-%m-%d %H:%M"),
        "last_status":  None,
        "last_locked":  None,
        "last_items":   {},
        "last_changed": None,
        "has_change":   False,
        "error":        None
    }

    try:
        ej_login()
        job_info = ej.get_job_info(job_no)
        if job_info:
            job_data  = job_info[0]
            job_id    = job_data.get("Id")
            job_state = job_data.get("JobState", "Unknown")
            watcher["label"]       = label or job_data.get("Caption", job_no)
            watcher["last_status"] = job_state
            watcher["last_locked"] = (job_state == "Proposed")

            try:
                items = ej.get_items_in_job(job_id)
                if items:
                    watcher["last_items"] = {
                        str(iid): {"name": i.get("name"), "qty": i.get("quantity")}
                        for iid, i in items.items()
                    }
            except Exception:
                pass
    except Exception as e:
        watcher["error"] = str(e)

    watchers.append(watcher)
    save_watchers(watchers)
    return redirect(url_for("polling"))

@app.route("/polling/remove", methods=["POST"])
def polling_remove():
    job_no   = request.form.get("job_no", "").strip()
    watchers = [w for w in load_watchers() if w["job_no"] != job_no]
    save_watchers(watchers)
    return redirect(url_for("polling"))

@app.route("/polling/clear_flag", methods=["POST"])
def polling_clear_flag():
    job_no   = request.form.get("job_no", "").strip()
    watchers = load_watchers()
    for w in watchers:
        if w["job_no"] == job_no:
            w["has_change"] = False
    save_watchers(watchers)
    return redirect(url_for("polling"))

@app.route("/polling/refresh", methods=["POST"])
def polling_refresh():
    watchers = load_watchers()
    if not ej_login():
        return redirect(url_for("polling"))

    for w in watchers:
        try:
            job_info = ej.get_job_info(w["job_no"])
            if not job_info:
                w["error"] = "Job not found"
                continue

            job_data   = job_info[0]
            job_id     = job_data.get("Id")
            new_status = job_data.get("JobState", "Unknown")
            new_locked = (new_status == "Proposed")

            new_items = {}
            try:
                items = ej.get_items_in_job(job_id)
                if items:
                    new_items = {
                        str(iid): {"name": i.get("name"), "qty": i.get("quantity")}
                        for iid, i in items.items()
                    }
            except Exception:
                pass

            status_changed = w["last_status"] != new_status
            locked_changed = w.get("last_locked") != new_locked
            items_changed  = w.get("last_items", {}) != new_items

            if status_changed or locked_changed or items_changed:
                w["has_change"]   = True
                w["last_changed"] = datetime.now().strftime("%Y-%m-%d %H:%M")

            w["last_status"] = new_status
            w["last_locked"] = new_locked
            w["last_items"]  = new_items
            w["error"]       = None

        except Exception as e:
            w["error"] = str(e)

    save_watchers(watchers)
    return redirect(url_for("polling"))


# -- Run --

if __name__ == "__main__":
    ensure_csv(ITEMS_CSV, CSV_COLUMNS)
    ensure_csv(CUSTOM_CSV, CUSTOM_COLUMNS)
    app.run(debug=True, host="0.0.0.0")
