# Inventory & Custom Barcode Management App

A web-based internal inventory management system built with **Flask**, **Python**, and **Bootstrap**, designed for **Creative Technology Group (CT) Intranet use**.  
It allows you to manage items, generate barcodes, create printable labels, and handle custom barcodes, with support for wildcard search.

---

## Features

- **Item Search**
  - Search inventory by name, description, or barcode
  - Supports wildcard searches (e.g., `ABC*` or `*123`)
  - View barcode labels directly in the browser
  - Print barcode labels with a single click

- **Custom Barcodes**
  - Add custom barcodes not tied to standard items
  - Generate and print custom labels
  - Delete individual labels or clear all custom barcodes
  - Supports wildcard search

- **Barcode & Label Generation**
  - Generates **Code128 barcodes** via [barcodeapi.org](https://barcodeapi.org/)
  - Creates **50mm × 25mm printable labels** with item name and barcode
  - Handles both standard items and custom barcodes

- **Polling**
  - Placeholder page for job polling and notifications

- **CSV-Based Storage**
  - Items and custom barcodes are stored in `items.csv` and `custom_barcodes.csv`
  - Automatically creates CSV files if missing
  - All barcode images and labels stored in `static/` directories

---

## Directory Structure

BarcodeManager/
│
├─ app.py # Main Flask application
├─ items.csv # Standard inventory CSV
├─ custom_barcodes.csv # Custom barcode CSV
├─ monofonto rg.otf # Font used for labels
├─ templates/
│ ├─ base_layout.html
│ ├─ index.html
│ ├─ custom_barcodes.html
│ └─ polling.html
├─ static/
│ ├─ barcode_images/ # Generated barcode images
│ ├─ labels/ # Standard labels
│ ├─ custom_barcodes/ # Custom barcode images
│ ├─ custom_labels/ # Custom labels
│ └─ icon.png
└─ README.md


---

## Installation

1. Clone the repository
```
git clone https://github.com/itsmejoshleach/BarcodeManager.git
cd BarcodeManager
```
2. Create a virtual environment
```
python -m venv venv
source venv/bin/activate   # Linux / macOS
venv\Scripts\activate      # Windows
```

3. Install dependencies
```
pip install -r requirements.txt
```

requirements.txt should include:

```
Flask
pandas
requests
Pillow
```

4. Ensure directories exist
The app will automatically create necessary directories in static/ on first run.

## Usage:
### Run the app
`python app.py`

### Access in browser
`http://127.0.0.1:5000/`

## Features

- Add Item: Click the + Add Item button in Item Search.

- Search Items: Use the search bar with wildcards (*) to filter items.

- Print Labels: Click Print Label to open a printable view.

- Custom Barcodes: Go to the Custom Barcodes tab to add or manage custom barcodes.

- Delete Labels: Delete individual labels or clear all custom barcodes from CSV and disk.

## Notes
- Labels are generated at 300 DPI, 50mm × 25mm size.

- Barcodes are retrieved from barcodeapi.org as PNGs.

- Font for labels is monofonto rg.otf; adjust FONT_PATH in app.py if needed.

- Wildcard searches use * to match any characters.

## License
- This project is for internal company/intranet use only.
© 2025-2026 Josh Leach

## Future Improvements
- Implement polling page with live job notifications.

- Add bulk CSV import/export.

- Add user authentication for access control.

- Improve label styling with additional templates or QR codes.