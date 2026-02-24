# easyjob WebAPI Documentation

## Base URL
```
http://<your_server>:<port>
```

---

## Authentication

### Get Access Token
```
POST /token
```

```python
import requests

url = "http://localhost:8008/token"
data = {
    "grant_type": "password",
    "username": "Administrator",
    "password": "123"
}

r = requests.post(url, data=data)
r.raise_for_status()
token = r.json()["access_token"]
print(token)
```

---

## Common

### Get Global Web Settings
```python
headers = {"Authorization": f"Bearer {token}"}
r = requests.get(
    "http://localhost:8008/api.json/Common/GetGlobalWebSettings",
    headers=headers
)
print(r.json())
```

---

## Projects

### List Projects
```python
r = requests.get(
    "http://localhost:8008/api.json/Projects/List/",
    headers=headers
)
print(r.json())
```

### Get Project Details
```python
project_id = 1
r = requests.get(
    f"http://localhost:8008/api.json/Projects/Details/{project_id}",
    headers=headers
)
print(r.json())
```

---

## Items

### List Items
```python
r = requests.get(
    "http://localhost:8008/api.json/Items/List/",
    headers=headers
)
print(r.json())
```

### Check Item Availability
```python
item_id = 5
r = requests.get(
    f"http://localhost:8008/api.json/Items/Avail/{item_id}",
    headers=headers
)
print(r.json())
```

---

## TimeCard

### Start Work Time
```python
payload = {
    "objectid": 123,
    "comment": "Started work"
}

r = requests.post(
    "http://localhost:8008/api.json/TimeCard/StartWorkTime",
    json=payload,
    headers=headers
)
print(r.json())
```

---

## Notes
- All requests require a Bearer token
- Responses are JSON
- `.json` suffix is mandatory in endpoints
