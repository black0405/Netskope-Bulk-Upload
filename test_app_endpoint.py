#!/usr/bin/env python3
"""
Quick check of /api/v2/events/datasearch/application -- one request, a few
records, no paging. Standalone (needs only `requests`).

Tries both auth header styles, so a 401 tells you whether it's the header
or the token's endpoint scope.

Usage:
    python test_app_endpoint.py                    -> last 24h, any user
    python test_app_endpoint.py user@company.com   -> last 24h, that user
"""

import sys
import time

import requests

API_TOKEN = "PUT_YOUR_API_TOKEN_HERE"
BASE_URL = "https://YOUR_TENANT.goskope.com"
ENDPOINT = "/api/v2/events/datasearch/application"
HOURS = 24
LIMIT = 5

if "PUT_YOUR" in API_TOKEN or "YOUR_TENANT" in BASE_URL:
    sys.exit("Set API_TOKEN and BASE_URL at the top of this file.")

end = int(time.time())
params = {"starttime": end - HOURS * 3600, "endtime": end,
          "limit": LIMIT, "offset": 0, "timeout": 180}
if len(sys.argv) > 1:
    params["query"] = f"user eq '{sys.argv[1]}'"

url = BASE_URL.rstrip("/") + ENDPOINT
print(f"GET {url}\nparams {params}\n")

for name, headers in (("bearer", {"Authorization": f"Bearer {API_TOKEN}"}),
                      ("netskope", {"Netskope-Api-Token": API_TOKEN})):
    resp = requests.get(url, params=params, timeout=200,
                        headers={**headers, "Accept": "application/json"})
    print(f"[{name}] HTTP {resp.status_code}")
    if not resp.ok:
        print(f"  {resp.text[:300]}\n")
        continue

    body = resp.json()
    rows = body.get("result", []) if isinstance(body, dict) else body
    print(f"  records: {len(rows)}  status: {body.get('status') if isinstance(body, dict) else '-'}")
    for r in rows:
        print(f"  {r.get('timestamp')}  {r.get('user')}  {r.get('app')}  {r.get('activity')}")
    if rows:
        print(f"  fields: {', '.join(sorted(rows[0]))}")
    print(f"\nOK -- use AUTH_MODE = \"{name}\"")
    break
else:
    print("Both failed. 401/403 on both = token lacks this endpoint: add "
          f"{ENDPOINT} to the token under Settings > Tools > REST API v2.")
