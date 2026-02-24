import os
import csv
import re
import requests
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

# ------------------------
# CONFIG
# ------------------------
ITEMS_CSV = "./items.csv"
CUSTOM_CSV = "./custom_barcodes.csv"

BARCODE_DIR = "static/barcode_images"
LABEL_DIR = "static/labels"
CUSTOM_BARCODE_DIR = "static/custom_barcode_images"
CUSTOM_LABEL_DIR = "static/custom_labels"

BARCODE_API = "https://barcodeapi.org/api/code128/{}"
FONT_PATH = "./monofonto rg.otf"

CSV_COLUMNS = ["Item Name", "Item Description / Alternate Names", "Barcode Number", "Barcode Image URL", "Barcode Image"]
CUSTOM_COLUMNS = ["Name", "Barcode", "Barcode Image URL", "Barcode Image"]

# Label config
LABEL_WIDTH_MM = 50
LABEL_HEIGHT_MM = 25
DPI = 300
TEXT_HEIGHT_FRACTION = 1 / 3
PADDING_MM = 0.5

# Ensure directories exist
for d in [BARCODE_DIR, LABEL_DIR, CUSTOM_BARCODE_DIR, CUSTOM_LABEL_DIR]:
    os.makedirs(d, exist_ok=True)

# ------------------------
# UTILS
# ------------------------
def mm_to_px(mm):
    return int((mm / 25.4) * DPI)

LABEL_WIDTH = mm_to_px(LABEL_WIDTH_MM)
LABEL_HEIGHT = mm_to_px(LABEL_HEIGHT_MM)
PADDING = mm_to_px(PADDING_MM)
TEXT_HEIGHT = int(LABEL_HEIGHT * TEXT_HEIGHT_FRACTION)

def sanitize_filename(name):
    return re.sub(r'[\\/:*?"<>| ]+', '_', name).strip()

def ensure_csv(path, columns):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(columns)

# ------------------------
# LOAD ITEMS
# ------------------------
def wildcard_to_regex(query):
    return re.escape(query).replace("\\*", ".*")

def load_items(query=""):
    ensure_csv(ITEMS_CSV, CSV_COLUMNS)
    df = pd.read_csv(ITEMS_CSV, dtype=str).fillna("")
    df["Item Name"] = df["Item Name"].str.strip()
    df["Item Description / Alternate Names"] = df["Item Description / Alternate Names"].str.strip()
    df["Barcode Number"] = df["Barcode Number"].str.strip()

    if query:
        regex_query = wildcard_to_regex(query)
        df = df[
            df["Item Name"].str.contains(regex_query, case=False, regex=True) |
            df["Item Description / Alternate Names"].str.contains(regex_query, case=False, regex=True) |
            df["Barcode Number"].str.contains(regex_query, case=False, regex=True)
        ]

    items = []
    for _, row in df.iterrows():
        name = row["Item Name"]
        if not name:
            continue
        safe = sanitize_filename(name)
        items.append({
            "name": name,
            "description": row["Item Description / Alternate Names"],
            "barcode": row["Barcode Number"],
            "label": f"labels/{safe}_label.png"
        })
    return items

def load_custom_barcodes(query=""):
    ensure_csv(CUSTOM_CSV, CUSTOM_COLUMNS)
    df = pd.read_csv(CUSTOM_CSV, dtype=str).fillna("")
    df["Name"] = df["Name"].str.strip()
    df["Barcode"] = df["Barcode"].str.strip()

    if query:
        regex_query = wildcard_to_regex(query)
        df = df[
            df["Name"].str.contains(regex_query, case=False, regex=True) |
            df["Barcode"].str.contains(regex_query, case=False, regex=True)
        ]

    items = []
    for _, row in df.iterrows():
        name = row["Name"]
        if not name:
            continue
        safe = sanitize_filename(name)
        label_path = f"custom_labels/{safe}_label.png"
        if not os.path.exists(os.path.join("static", label_path)):
            continue
        items.append({
            "name": name,
            "barcode": row["Barcode"],
            "label": label_path
        })
    return items

# ------------------------
# BARCODE / LABEL GENERATION
# ------------------------
def generate_barcode(barcode, name, custom=False):
    safe = sanitize_filename(name)
    dir_path = CUSTOM_BARCODE_DIR if custom else BARCODE_DIR
    path = os.path.join(dir_path, f"{safe}.png")
    url = BARCODE_API.format(barcode)
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    return path

def create_label(barcode_img_path, name, custom=False):
    safe = sanitize_filename(name)
    dir_path = CUSTOM_LABEL_DIR if custom else LABEL_DIR
    out_path = os.path.join(dir_path, f"{safe}_label.png")

    label = Image.new("1", (LABEL_WIDTH, LABEL_HEIGHT), 1)
    barcode = Image.open(barcode_img_path).convert("1")

    max_w = LABEL_WIDTH - 2 * PADDING
    max_h = LABEL_HEIGHT - TEXT_HEIGHT - 2 * PADDING
    bw, bh = barcode.size
    scale = min(max_w / bw, max_h / bh)
    barcode = barcode.resize((int(bw * scale), int(bh * scale)), Image.LANCZOS)
    label.paste(barcode, ((LABEL_WIDTH - barcode.width) // 2, PADDING))

    draw = ImageDraw.Draw(label)
    font_size = 80
    font = ImageFont.truetype(FONT_PATH, font_size)
    while draw.textbbox((0,0), name, font=font)[2] > LABEL_WIDTH - 10:
        font_size -= 2
        font = ImageFont.truetype(FONT_PATH, font_size)

    bbox = draw.textbbox((0,0), name, font=font)
    text_x = (LABEL_WIDTH - (bbox[2]-bbox[0])) // 2
    text_y = LABEL_HEIGHT - TEXT_HEIGHT + (TEXT_HEIGHT - (bbox[3]-bbox[1])) // 2
    draw.text((text_x, text_y), name, font=font, fill=0)
    label.save(out_path)
    return out_path

# ------------------------
# ROUTES
# ------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    query = request.form.get("search", "").strip() if request.method=="POST" else ""
    items = load_items(query)
    return render_template("index.html", items=items, query=query, page="items")

@app.route("/add", methods=["POST"])
def add_item():
    name = request.form.get("name","").strip()
    desc = request.form.get("description","").strip()
    barcode = request.form.get("barcode","").strip()
    if not name or not barcode:
        return "Missing fields",400
    ensure_csv(ITEMS_CSV, CSV_COLUMNS)
    with open(ITEMS_CSV,"a",newline="",encoding="utf-8") as f:
        csv.writer(f).writerow([name,desc,barcode,"",""])
    barcode_path = generate_barcode(barcode,name,custom=False)
    create_label(barcode_path,name,custom=False)
    return redirect(url_for("index"))

# ------------------------
# CUSTOM BARCODES
# ------------------------
@app.route("/custom_barcodes", methods=["GET","POST"])
def custom_barcodes():
    query = ""
    if request.method=="POST":
        query = request.form.get("search","").strip()
        if request.form.get("clear")=="1":
            items = load_custom_barcodes()
            for i in items:
                try:
                    os.remove(os.path.join(CUSTOM_BARCODE_DIR, sanitize_filename(i["name"])+".png"))
                    os.remove(os.path.join(CUSTOM_LABEL_DIR, sanitize_filename(i["name"])+".png"))
                except FileNotFoundError:
                    pass
            with open(CUSTOM_CSV,"w",newline="",encoding="utf-8") as f:
                csv.writer(f).writerow(CUSTOM_COLUMNS)
            return render_template("custom_barcodes.html", items=[], query="", page="custom")
    items = load_custom_barcodes(query)
    return render_template("custom_barcodes.html", items=items, query=query, page="custom")

@app.route("/add_custom_barcode", methods=["POST"])
def add_custom_barcode():
    name = request.form.get("name","").strip()
    barcode = request.form.get("barcode","").strip()
    if not name or not barcode:
        return "Missing fields",400
    ensure_csv(CUSTOM_CSV, CUSTOM_COLUMNS)
    with open(CUSTOM_CSV,"a",newline="",encoding="utf-8") as f:
        csv.writer(f).writerow([name,barcode,"",""])
    barcode_path = generate_barcode(barcode,name,custom=True)
    create_label(barcode_path,name,custom=True)
    return redirect(url_for("custom_barcodes"))

# ------------------------
# DELETE LABEL (items/custom)
# ------------------------
@app.route("/delete_label", methods=["POST"])
def delete_label():
    filepath = request.form.get("filepath","")
    page_type = request.form.get("page_type","items")
    if not filepath:
        return "Missing filepath",400

    try:
        os.remove(os.path.join("static", filepath))
    except FileNotFoundError:
        pass

    name = os.path.splitext(os.path.basename(filepath))[0].replace("_label","")
    safe_name = sanitize_filename(name)
    if page_type=="items":
        csv_path = ITEMS_CSV
        png_dir = BARCODE_DIR
    else:
        csv_path = CUSTOM_CSV
        png_dir = CUSTOM_BARCODE_DIR

    try:
        os.remove(os.path.join(png_dir,f"{safe_name}.png"))
    except FileNotFoundError:
        pass

    df = pd.read_csv(csv_path)
    if page_type=="items":
        df = df[df["Item Name"].str.strip() != name]
    else:
        df = df[df["Name"].str.strip() != name]
    df.to_csv(csv_path,index=False)
    return redirect(url_for("index") if page_type=="items" else url_for("custom_barcodes"))

# ------------------------
# Polling placeholder
# ------------------------
@app.route("/polling")
def polling():
    return render_template("polling.html", page="polling")

# ------------------------
# RUN
# ------------------------
if __name__=="__main__":
    ensure_csv(ITEMS_CSV,CSV_COLUMNS)
    ensure_csv(CUSTOM_CSV,CUSTOM_COLUMNS)
    app.run(debug=True,host="0.0.0.0")
