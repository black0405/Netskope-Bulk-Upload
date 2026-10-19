# Netskope Bulk Upload

Pulls Netskope UBA alerts for bulk upload / download, then pulls the
application events for the users in those alerts and maps them by email.

## Requires

The sibling repo [Netskope-API](https://github.com/black0405/Netskope-API)
checked out next to this one (the HTTP/paging code is imported from it):

```
some-folder/
  Netskope-API/
  netskope bulk upload/      <- this repo
```

`pip install requests pandas`

## Setup

Set `API_TOKEN` and `BASE_URL` at the top of `bulk_upload_uba.py`.
Do not commit the real token.

## Usage

```
python bulk_upload_uba.py               # yesterday
python bulk_upload_uba.py 2026-10-18    # one day
python bulk_upload_uba.py --days 7      # past 7 full days, ending yesterday
python bulk_upload_uba.py --selftest    # offline check
```

## Output (`output/`)

| File | Contents |
|---|---|
| `UBA_BulkTransfer_<range>.csv` | UBA alerts whose name/activity mentions upload or download |
| `UBA_AppEvents_<range>.csv` | Application events for those users |
| `UBA_Mapped_<range>.csv` | Alerts left-joined to events by email |

Exit codes: 0 ok, 1 config/date error, 2 Netskope API failure, 3 no matching UBA alerts.
