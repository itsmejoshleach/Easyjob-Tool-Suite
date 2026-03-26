# Inventory Management & EasyJob Integration

A Flask-based internal inventory system designed for Creative Technology Group workflows.  
This app integrates with the EasyJob API to provide item search, stock visibility, job tracking, and barcode utilities.

---

## 🚀 Features

- 🔍 **Item Search**
  - Search EasyJob inventory
  - View item details and metadata

- 📦 **Stock Check**
  - Real-time stock levels (warehouse, on jobs, workshop)
  - Availability calculations via EasyJob API

- 👀 **Job Watching**
  - Monitor job changes (polling system)
  - Track item allocations dynamically

- 🏷️ **Barcode Tools**
  - Barcode lookup (RentalPoint → EasyJob device)
  - Custom barcode generation & management

- 📥 **Import System**
  - Bulk import items into local system
  - Sync from EasyJob with progress tracking

- 🔄 **EasyJob Sync**
  - Background sync with progress polling
  - Duplicate-safe item ingestion
  - Error tracking and reporting

---

## 🧱 Project Structure

```
.
├── app.py                  # Main Flask app
├── easyjob.py             # EasyJob API helper module
├── templates/
│   ├── base_layout.html   # Main UI layout (Bootstrap-based)
│   └── *.html             # Page templates
├── static/
│   ├── barcode_images/    # Generated barcodes
│   ├── background.jpg
│   └── icon.png
├── items.csv              # Local item cache
├── custom_barcodes.csv    # Custom barcode mappings
├── requirements.txt
└── .env                   # Environment config (not committed)
```

---

## ⚙️ Setup

### 1. Clone the repo

```bash
git clone https://github.com/itsmejoshleach/Easyjob-Tool-Suite
cd inventory-app
```

---

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate     # Linux / Mac
venv\Scripts\activate        # Windows
```

---

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

### 4. Configure environment

Create a `.env` file:

```env
EJ_BASE_URL=https://your-easyjob-instance
EJ_USERNAME=your_username
EJ_PASSWORD=your_password
EJ_Access_Token=
```

> Token is automatically populated after first authentication.

---

### 5. Run the app

```bash
python app.py
```

App will be available at:

```
http://127.0.0.1:5000
```

---

## 🔐 Authentication Flow

- Uses EasyJob OAuth token (`/token`)
- Token is:
  - Cached in memory
  - Persisted to `.env`
- Automatically refreshes on `401 Unauthorized`

---

## 🔌 EasyJob API Helper (`easyjob.py`)

### Key Capabilities

- Authentication + token persistence
- Generic request wrapper with retry
- Item + stock endpoints
- Device & barcode resolution
- Job lookup & details
- Availability + stock summaries

### Example Usage

```python
from easyjob import quick_login, get_stock_summary_by_name

quick_login()
results = get_stock_summary_by_name("LED Panel")

for item in results:
    print(item["name"], item["warehouse"])
```

---

## 🔄 Sync System

- Triggered from UI ("Sync from EasyJob")
- Runs in background
- Progress tracked via:

```
/sync_status
```

### Status includes:

- Processed / total items
- Items added
- Items skipped
- Errors (if any)
- Last sync timestamp

---

## 📡 API Endpoints (Internal)

| Endpoint         | Method | Description                  |
|----------------|--------|------------------------------|
| `/sync_items`   | POST   | Start EasyJob sync           |
| `/sync_status`  | GET    | Get sync progress            |
| `/`             | GET    | Item search page             |
| `/stock`        | GET    | Stock checker                |
| `/polling`      | GET    | Job watching UI              |

---

## 🧠 Design Notes

- **Token handling** is automatic and resilient
- **Search pagination workaround** implemented via A-Z sweep
- **UI** uses Bootstrap 5 + glassmorphism styling
- Built for **internal intranet deployment**

---

## ⚠️ Known Limitations

- EasyJob API result limits require multi-query sweeping
- SSL verification disabled by default (`VERIFY_CERT = False`)
- No authentication layer on Flask app (intended for internal network)

---

## 🛠️ Future Improvements

- See TODO File

---

## 👨‍💻 Author

**Josh Leach**  
Creative Technology Group UK

📧 jleach@ctlondon.com  

---

## 📄 License

GNU GENERAL PUBLIC LICENSE