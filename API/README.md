# EasyJob API Helper

A lightweight Python helper module for interacting with the EasyJob API. This wrapper simplifies authentication, querying inventory, jobs, devices, and stock availability while handling token management and request retries automatically.

---

## 🚀 Features

* 🔐 Token-based authentication with auto-refresh
* 📦 Item and inventory lookup
* 🔎 Barcode → Device ID conversion
* 📊 Stock availability summaries
* 📅 Job and calendar queries
* 🔁 Automatic retry on expired tokens
* 🧰 Helper functions for common EasyJob workflows

---

## 📦 Installation

### 1. Clone or download the project

```bash
git clone <your-repo-url>
cd easyjob-api-helper
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

**Required packages:**

* `requests`
* `python-dotenv`
* `urllib3`

---

## ⚙️ Configuration

Create a `.env` file in the same directory as the script:

```env
EJ_BASE_URL=https://your-easyjob-instance
EJ_USERNAME=your_username
EJ_PASSWORD=your_password
EJ_Access_Token=
```

> ⚠️ `EJ_Access_Token` will be automatically populated after authentication.

---

## 🔑 Authentication

### Quick Login

```python
from easyjob_helper import quick_login

quick_login(
    base_url="https://your-instance",
    username="user",
    password="pass",
    verify_cert=False
)
```

### Manual Authentication

```python
from easyjob_helper import authenticate

token = authenticate()
```

---

## 📦 Item Functions

### Get all items

```python
get_all_items("LED Panel")
```

### Get full inventory sweep

```python
get_all_items_full()
```

### Get item details

```python
get_item_details(item_id)
```

### Get accessories

```python
get_item_accessories(item_id)
```

### Get availability

```python
get_item_availability(item_id)
```

---

## 📊 Stock Summary

### Get structured stock data

```python
get_stock_summary(item_id)
```

Returns:

```json
{
  "item_id": 123,
  "total": 50,
  "warehouse": 30,
  "on_jobs": 15,
  "workshop": 5
}
```

### Search by item name

```python
get_stock_summary_by_name("Aputure 300D")
```

### Print formatted report

```python
print_stock_summary("Aputure")
```

---

## 🔍 Device & Barcode Functions

### Get device info from barcode

```python
get_device_info("BP2/205")
```

### Convert barcode → device ID

```python
_convert_barcode_to_device_id("BP2/205")
```

---

## 📅 Job Functions

### Search jobs

```python
get_job_info("3138.01")
```

### Get job details

```python
get_job_details(job_id)
```

### Get items in a job

```python
get_items_in_job(job_id)
```

### Pretty print job items

```python
print_items_in_job("3138.01")
```

---

## 📆 Calendar

```python
get_calendar("2025-01-01", days=14)
```

---

## 🔧 Utility Functions

### Test API connection

```python
test_connection()
```

### Get device list for an item

```python
get_device_list(item_id)
```

---

## 🔄 Internal Behaviour

* Automatically retries requests on `401 Unauthorized`
* Saves refreshed tokens back into `.env`
* Handles URL encoding for barcodes and search queries
* Supports wildcard searches (`*search*`)

---

## ⚠️ Notes

* SSL verification is disabled by default (`VERIFY_CERT = False`)

  * Enable this in production environments
* API response formats may vary depending on EasyJob version
* Some fields (e.g. `Service`) require additional modules in EasyJob

---

## 🧠 Example Workflow

```python
quick_login()

# Find item
items = get_all_items("LED Panel")
item_id = items[0]["Id"]

# Get stock summary
summary = get_stock_summary(item_id)

print(summary)
```

---

## 📄 License

[GNU GENERAL PUBLIC LICENSE](https://www.gnu.org/licenses/gpl-3.0.en.html)

---

## 👤 Author

Josh Leach / Built For CT (Creative Technology Group) Intranet Usage

---

