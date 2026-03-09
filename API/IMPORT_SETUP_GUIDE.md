# Project Structure & Import Setup

## Recommended Directory Structure

```
project_root/
├── API/
│   ├── __init__.py          # Makes API a Python package
│   ├── easyjob.py           # EasyJob API functions
│   ├── main.py              # API testing/examples
│   └── requirements.txt
├── Web App/
│   ├── app.py               # Flask application
│   ├── requirements.txt
│   ├── templates/
│   │   ├── base_layout.html
│   │   ├── index.html
│   │   ├── custom_barcodes.html
│   │   └── polling.html
│   └── static/
│       ├── barcode_images/
│       ├── labels/
│       ├── custom_barcode_images/
│       └── custom_labels/
├── .env                     # Environment variables (shared)
└── README.md
```

## Method 1: Add API to Python Path (Recommended)

### Create API/__init__.py
```python
# API/__init__.py
# This makes API a proper Python package
```

### In Web App/app.py, add this at the top:
```python
import sys
import os

# Add the parent directory to Python path so we can import from API
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now you can import the easyjob module
from API import easyjob

# Use it in your Flask routes
@app.route("/stock_check", methods=["POST"])
def stock_check():
    barcode = request.form.get("barcode", "").strip()
    
    # Call EasyJob API functions
    device_info = easyjob.get_device_info(barcode)
    
    return render_template("stock_check.html", device=device_info)
```

## Method 2: Install as Package (Alternative)

### Create API/setup.py
```python
from setuptools import setup, find_packages

setup(
    name="easyjob-api",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "requests",
        "python-dotenv",
        "urllib3"
    ]
)
```

### Install in development mode
```bash
cd API
pip install -e .
```

### Then in Web App/app.py:
```python
import easyjob

# Use directly
device_info = easyjob.get_device_info("BP2/205")
```

## Method 3: Symbolic Link (Quick & Dirty)

```bash
cd "Web App"
ln -s ../API/easyjob.py easyjob.py
```

Then in app.py:
```python
import easyjob
```

## Recommended: Method 1

Method 1 is the cleanest for this project structure. Here's the complete setup:

1. Create `API/__init__.py` (empty file)
2. Update `Web App/app.py` to add the parent directory to sys.path
3. Import and use: `from API import easyjob`

This keeps your API code in one place and makes it reusable across different parts of your application.
