# EasyJob Tool Suite - Inventory & Barcode Management

Internal web application for the **Creative Technology Group (CT)** intranet.  
Built with Flask, Python, and Bootstrap. Integrates with **EasyJob** via its WebAPI.

---

## Features

### Item Search
- Search inventory by name, description, or barcode (wildcard `*` supported)
- Paginated results (25 per page)
- **More Info** modal per item - description, how-to steps, photo URL, accessories
- Edit item name, description, and barcode inline
- Print 50mm × 25mm barcode labels directly from the browser
- Delete individual items and their labels

### Stock Check
- Smart search - accepts RP barcodes (`BP2/205`), `@si` device numbers, EJ item IDs, or plain name search
- Shows total owned, in warehouse, and on jobs
- Resolves device barcodes to stock-type level automatically
- Raw API response visible to admins only

### Job Watching
- Watch specific jobs for status or item list changes
- Shipping status derived from `DayTimeOut` / `DayTimeIn`:
  - **Upcoming** - before DayTimeOut
  - **Shipped** - past DayTimeOut, before DayTimeIn
  - **Past Return Date** - past DayTimeIn, not yet marked returned
  - **Returned** - manually confirmed by staff
- Mark as Returned button; acknowledging a "Past Return Date" change auto-deletes the watcher
- Per-user watchers - each user sees only their own; admins can toggle "Show All Users"

### Calendar Watch
- Fetches 14 days of EasyJob calendar per user (using their own EJ credentials)
- Filters to job-relevant entries only (Prep, On Site, Onsite)
- Per-user unseen notification list - dismissible individually or all at once
- Fully isolated - one user's refresh does not affect another's view

### Custom Barcodes
- Create barcodes for items not in the standard inventory
- Generate and print labels
- Delete individually or clear all

### Barcode Finder
- Paste a list of barcodes to find (one per line)
- Scan with a Bluetooth or USB scanner (keyboard input mode)
- Beeps on match (two rising tones), no match (low buzz), all found (three ascending tones)
- Visual progress bar and per-barcode tick-off list

### Import Items (Admin)
- Fetch full UK item catalogue from EasyJob via A–Z sweep
- Saves to `ej_export.json` on disk - no large HTTP upload needed
- Per-item DeviceList check to distinguish barcoded vs non-barcoded items
- Skips items already in CSV; skips regional items (`<AUS>`, `<ES>`, `<USA>`, etc.)
- Live progress polling via `/import/status`

### Sync from EasyJob (Admin)
- Background sync of EasyJob items into `items.csv`
- Live progress shown in sidebar
- Same barcoded/non-barcoded detection as Import

### User Management (Admin)
- Local username/password accounts (bcrypt via Werkzeug)
- Two roles: **Admin** (all features) and **User** (standard features)
- Per-user EasyJob credentials (username + encrypted password)
- Add, edit, delete users via UI
- Passwords shown/hidden with toggle

---

## Roles & Access

| Feature | User | Admin |
|---|---|---|
| Item Search | ✅ | ✅ |
| Stock Check | ✅ | ✅ |
| Job Watching | ✅ | ✅ |
| Calendar Watch | ✅ | ✅ |
| Custom Barcodes | ✅ | ✅ |
| Barcode Finder | ✅ | ✅ |
| Raw API response | ❌ | ✅ |
| Import Items | ❌ | ✅ |
| Sync from EasyJob | ❌ | ✅ |
| User Management | ❌ | ✅ |

---

## Directory Structure

```
EasyJob Tool Suite/
│
├── Web App/
│   ├── app.py                   # Main Flask application
│   ├── items.csv                # Inventory (auto-created)
│   ├── custom_barcodes.csv      # Custom barcodes (auto-created)
│   ├── item_profiles.json       # More Info content per item
│   ├── users.json               # User accounts (encrypted EJ passwords)
│   ├── job_watchers.json        # Per-user job watcher state
│   ├── calendar_watch.json      # Per-user calendar watch state
│   ├── sync_status.json         # EJ sync progress
│   ├── import_status.json       # Import progress
│   ├── fetch_status.json        # Fetch metadata (items in ej_export.json)
│   ├── ej_export.json           # Last EJ item fetch (can be large)
│   ├── monofonto rg.otf         # Font for barcode labels
│   ├── templates/
│   │   ├── base_layout.html
│   │   ├── index.html
│   │   ├── stock_check.html
│   │   ├── _stock_result_card.html
│   │   ├── polling.html
│   │   ├── custom_barcodes.html
│   │   ├── barcode_finder.html
│   │   ├── import.html
│   │   ├── login.html
│   │   ├── admin_users.html
│   │   └── 403.html
│   └── static/
│       ├── background.jpg
│       ├── icon.png
│       ├── barcode_images/
│       ├── labels/
│       ├── custom_barcode_images/
│       └── custom_labels/
│
└── API/
    ├── easyjob.py               # EasyJob WebAPI helper module
    └── requirements.txt
```

---

## Installation

**1. Clone the repository**
```
git clone https://github.com/itsmejoshleach/BarcodeManager.git
cd "EasyJob Tool Suite"
```

**2. Create a virtual environment**
```
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux / macOS
```

**3. Install dependencies**
```
pip install -r "Web App/requirements.txt"
```

`requirements.txt`:
```
Flask
pandas
requests
Pillow
python-dotenv
cryptography
```

**4. Create `.env`**

Create a `.env` file in the `Web App/` directory:
```
EJ_BASE_URL=https://your-easyjob-server:port
SECRET_KEY=your-flask-secret-key
FIELD_ENCRYPT_KEY=your-fernet-encryption-key
```

Generate `SECRET_KEY`:
```
python -c "import secrets; print(secrets.token_hex(32))"
```

Generate `FIELD_ENCRYPT_KEY`:
```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**5. Create the initial admin account**

Create `Web App/users.json`:
```json
{
  "admin": {
    "password_hash": "generate-this-below",
    "role": "admin",
    "display_name": "Admin",
    "ej_username": "DOMAIN\\your.username",
    "ej_password": "generate-this-below"
  }
}
```

Generate password hash:
```
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your-password'))"
```

Generate encrypted EJ password:
```
python -c "
import os; from dotenv import load_dotenv; load_dotenv()
from cryptography.fernet import Fernet
f = Fernet(os.getenv('FIELD_ENCRYPT_KEY').encode())
print(f.encrypt('your-ej-password'.encode()).decode())
"
```

Or just create the account via the admin UI after first login and re-enter credentials there.

---

## Running

```
cd "Web App"
python app.py
```

Access at `http://127.0.0.1:5000`

Default admin login: set manually in `users.json` (see above).  
Change credentials immediately via **User Management** after first login.

---

## EasyJob Credentials

Each user account has their own EasyJob username and password, set in User Management.  
EJ passwords are stored **encrypted** in `users.json` using Fernet symmetric encryption.  
The encryption key lives only in `.env` - losing it means EJ passwords must be re-entered.

EJ usernames are typically prefixed: `DOMAIN\\firstname.lastname`

EasyJob tokens are cached per-user in the Flask session cookie - one authentication per login session, not per request.

---

## Notes

- Labels are generated at 300 DPI, 50mm × 25mm
- Barcodes fetched from [barcodeapi.org](https://barcodeapi.org/) as Code128 PNGs
- Font for labels: `monofonto rg.otf` - adjust `FONT_PATH` in `app.py` if needed
- The EasyJob item sweep uses `*<UK> X*` wildcard queries per character to work around EJ's result cap
- SSL verification is disabled for EJ API calls (`VERIFY_CERT = False`) - intended for internal/self-signed certs

---

## License

Built for internal use  - Creative Technology Group.
© 2025–2026 Josh Leach