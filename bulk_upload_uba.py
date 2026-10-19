#!/usr/bin/env python3
"""
Netskope UBA bulk upload / download -> application events mapping.

  1. Pull UBA alerts for one day      (/api/v2/events/datasearch/alert,
                                        query: alert_type eq 'uba')
     and keep only the upload / download ones (alert_name or activity).
  2. Take the distinct user emails from those alerts and pull that day's
     application events for just those users
                                       (/api/v2/events/datasearch/application,
                                        query: user in ['a@x', 'b@y', ...]).
  3. Left-join the application events onto the UBA alerts by email.

Outputs (in ./output):
    UBA_BulkTransfer_<day>.csv     every matching UBA alert, all fields
    UBA_AppEvents_<day>.csv        application events for those users
    UBA_Mapped_<day>.csv           UBA alert columns + app event columns

The HTTP, retry, paging and time-window logic is NOT duplicated here: it is
imported from ../Netskope-API/export_genai_page_bytes.py, so a fix made there
applies to this script too. Keep both folders side by side.

Usage:
    python bulk_upload_uba.py               -> yesterday
    python bulk_upload_uba.py 2026-10-18    -> that day
    python bulk_upload_uba.py --days 7      -> past 7 full days (to yesterday)
    python bulk_upload_uba.py --selftest    -> offline check of filter + join
"""

import os
import sys
import time
from typing import Any, Dict, List

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "Netskope-API"))
import export_genai_page_bytes as ns  # noqa: E402

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
# SECURITY: the token lives in this file -- keep it out of git (chmod 600).
API_TOKEN: str = "PUT_YOUR_API_TOKEN_HERE"
BASE_URL: str = "https://YOUR_TENANT.goskope.com"
AUTH_MODE: str = "bearer"                 # flip to "netskope" on 401s

ALERT_ENDPOINT: str = "/api/v2/events/datasearch/alert"
APP_ENDPOINT: str = "/api/v2/events/datasearch/application"
UBA_QUERY: str = "alert_type eq 'uba'"

# A UBA alert is kept when its alert_name or activity contains any of these
# (case-insensitive), e.g. "Bulk Upload", "Bulk Download of Files".
UBA_KEYWORDS: List[str] = ["upload", "download"]

# Application events are limited to these activities (server-side filter),
# so Browse, Login, mail etc. never come back.
APP_ACTIVITIES: List[str] = ["Upload", "Download"]

# Users per application-events query. Keeps the `user in [...]` filter
# (and the URL) a sane length.
EMAIL_BATCH: int = 50

OUTPUT_DIR: str = os.path.join(SCRIPT_DIR, "output")
LOG_DIR: str = os.path.join(SCRIPT_DIR, "logs")

# Columns kept in the mapped file. Missing fields export blank.
UBA_COLUMNS: List[str] = ["user", "alert_name", "activity", "app",
                          "timestamp", "severity", "count", "_id"]
APP_COLUMNS: List[str] = ["app", "activity", "object_type", "object",
                          "file_size", "url", "timestamp",
                          "organization_unit", "_id"]

# ---------------------------------------------------------------------------


def email_key(value: Any) -> str:
    """Normalised join key: 'User@X.com ' and 'user@x.com' are one person."""
    return "" if value is None else str(value).strip().casefold()


def filter_uba(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep UBA alerts whose alert_name/activity mentions a keyword."""
    keep = []
    for row in rows:
        text = f"{row.get('alert_name', '')} {row.get('activity', '')}".lower()
        if any(k in text for k in UBA_KEYWORDS):
            keep.append(row)
    return keep


def map_events(uba_rows: List[Dict[str, Any]],
               app_rows: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Left-join application events onto UBA alerts by email. A UBA alert with
    no application events still appears once, with the app columns blank.
    """
    uba = pd.DataFrame(uba_rows).reindex(columns=UBA_COLUMNS)
    app = pd.DataFrame(app_rows).reindex(columns=["user"] + APP_COLUMNS)
    uba.columns = [f"UBA {c}" for c in uba.columns]
    app.columns = ["user"] + [f"Event {c}" for c in APP_COLUMNS]

    uba["_key"] = uba["UBA user"].map(email_key)
    app["_key"] = app.pop("user").map(email_key)
    mapped = uba.merge(app, on="_key", how="left").drop(columns="_key")

    for col in ("UBA timestamp", "Event timestamp"):
        mapped[col] = mapped[col].map(ns.format_epoch)
    return mapped.fillna("")


def resolve_range():
    """
    --days N -> the N full days ending yesterday (today is excluded, it's
    still filling up). Otherwise the usual single day: CLI date or yesterday.
    """
    if "--days" not in sys.argv:
        return ns.prompt_for_date_range()
    days = int(sys.argv[sys.argv.index("--days") + 1])
    if days < 1:
        raise ValueError("--days must be 1 or more")
    end = ns.local_midnight(time.time())
    start = end
    for _ in range(days):                 # DST-safe, unlike end - days*86400
        start = ns.previous_local_midnight(start)
    day = lambda t: time.strftime("%Y-%m-%d", time.localtime(t))
    last = ns.previous_local_midnight(end)
    label = day(start) if days == 1 else f"{day(start)}_to_{day(last)}"
    return start, end - ns.BOUNDARY_TRIM, label


def fetch(session, endpoint: str, query: str, start: int, end: int,
          stats: Dict[str, int]) -> List[Dict[str, Any]]:
    ns.ENDPOINT_PATH = endpoint
    return [ns.flatten_record(r)
            for r in ns.fetch_all(session, query, start, end, stats)]


def write(rows, path: str) -> None:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8")
    ns.log.info("wrote      %s (%d rows)", path, len(frame))


def main() -> int:
    for name in ("API_TOKEN", "BASE_URL", "AUTH_MODE"):
        setattr(ns, name, globals()[name])
    ns.LOG_DIR, ns.LOG_BASENAME = LOG_DIR, "bulk_upload_uba.log"
    ns.SEND_FIELDS_PARAM = False      # ns's field list is for page events
    ns.setup_logging(time.strftime("%H%M%S"))

    if "PUT_YOUR_API_TOKEN" in API_TOKEN or "YOUR_TENANT" in BASE_URL:
        ns.log.error("CONFIG ERROR: set API_TOKEN / BASE_URL at the top of %s",
                     os.path.basename(__file__))
        return 1

    try:
        start, end, label = resolve_range()
    except (ValueError, IndexError) as exc:
        ns.log.error("BAD DATE / --days: %s (use --days 7 or YYYY-MM-DD)", exc)
        return 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = lambda kind: os.path.join(OUTPUT_DIR, f"UBA_{kind}_{label}.csv")
    session = ns.build_session()
    stats: Dict[str, int] = {"calls": 0}

    try:
        ns.log.info("day        %s", label)
        alerts = filter_uba(fetch(session, ALERT_ENDPOINT, UBA_QUERY,
                                  start, end, stats))
        ns.log.info("UBA alerts matching %s: %d", UBA_KEYWORDS, len(alerts))
        if not alerts:
            return 3
        write(alerts, out("BulkTransfer"))

        emails = sorted({str(a["user"]).strip() for a in alerts if a.get("user")})
        ns.log.info("users      %d", len(emails))
        events: List[Dict[str, Any]] = []
        activity = ns.build_term("activity", "in", ",".join(APP_ACTIVITIES))
        for i in range(0, len(emails), EMAIL_BATCH):
            users = ns.build_term("user", "in", ",".join(emails[i:i + EMAIL_BATCH]))
            query = f"{users} and {activity}"
            events += fetch(session, APP_ENDPOINT, query, start, end, stats)
        write(events, out("AppEvents"))
    except ns.ApiError as exc:
        ns.log.error("NETSKOPE FAILED: %s", exc)
        return 2

    write(map_events(alerts, events), out("Mapped"))
    ns.log.info("API calls  %d", stats["calls"])
    return 0


def selftest() -> None:
    alerts = filter_uba([
        {"user": "A@x.com", "alert_name": "Bulk Upload", "app": "Box"},
        {"user": "b@x.com", "alert_name": "Bulk Download", "app": "Drive"},
        {"user": "c@x.com", "alert_name": "Bulk Delete", "app": "Box"},
    ])
    assert [a["user"] for a in alerts] == ["A@x.com", "b@x.com"]

    mapped = map_events(alerts, [
        {"user": "a@x.com ", "app": "ChatGPT", "activity": "Upload"},
        {"user": "a@x.com", "app": "Gemini", "activity": "Post"},
        {"user": "z@x.com", "app": "Box", "activity": "Upload"},
    ])
    assert len(mapped) == 3                       # 2 for A, 1 blank for b
    assert list(mapped["Event app"]) == ["ChatGPT", "Gemini", ""]
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    sys.exit(main())
