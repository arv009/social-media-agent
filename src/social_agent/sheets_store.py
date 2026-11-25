"""Permanent storage in a Google Sheet (Streamlit Cloud's disk resets on every restart).

Uses a Google service account: a robot account only this app uses. Setup:
  1. Google Cloud Console: enable the Google Sheets API, create a service account, add a JSON key.
  2. Create a Google Sheet and share it with the service account's email (Editor).
  3. Secrets: DATA_SHEET_URL = "<the sheet's link>" and the key as GOOGLE_SERVICE_ACCOUNT_JSON
     (or as a [gcp_service_account] section).
Each kind of data gets its own tab, created automatically with a header row.
"""
import json
import os
import re

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsError(Exception):
    pass


def sheet_id() -> str | None:
    raw = os.getenv("DATA_SHEET_URL") or os.getenv("DATA_SHEET_ID") or ""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", raw)
    return m.group(1) if m else (raw.strip() or None)


def _service_account_info() -> dict | None:
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError as e:
        raise SheetsError("GOOGLE_SERVICE_ACCOUNT_JSON isn't valid JSON. Paste the whole key file between "
                          "triple quotes in Secrets.") from e


def configured() -> bool:
    return bool(sheet_id() and os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))


def service_account_email() -> str | None:
    try:
        info = _service_account_info()
    except SheetsError:
        return None
    return info.get("client_email") if info else None


_service = None


def _sheets():
    global _service
    if _service is None:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        info = _service_account_info()
        if not info or not sheet_id():
            raise SheetsError("Google Sheets isn't set up (DATA_SHEET_URL and GOOGLE_SERVICE_ACCOUNT_JSON).")
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _service = build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()
    return _service


def _call(request):
    try:
        return request.execute()
    except Exception as e:  # noqa: BLE001 - turn Google errors into one readable message
        msg = str(e)
        if "403" in msg or "PERMISSION_DENIED" in msg:
            raise SheetsError(f"No access to the sheet. Share it with {service_account_email()} as Editor.") from e
        if "404" in msg:
            raise SheetsError("Sheet not found. Check DATA_SHEET_URL.") from e
        if "SERVICE_DISABLED" in msg or "has not been used" in msg:
            raise SheetsError("The Google Sheets API isn't enabled for the service account's project.") from e
        raise SheetsError(f"Google Sheets error: {msg[:200]}") from e


def _ensure_tab(tab: str, header: list[str]) -> None:
    meta = _call(_sheets().get(spreadsheetId=sheet_id(), fields="sheets.properties.title"))
    titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if tab not in titles:
        _call(_sheets().batchUpdate(spreadsheetId=sheet_id(),
                                    body={"requests": [{"addSheet": {"properties": {"title": tab}}}]}))
    _call(_sheets().values().update(spreadsheetId=sheet_id(), range=f"'{tab}'!A1",
                                    valueInputOption="RAW", body={"values": [header]}))


def read_rows(tab: str, header: list[str]) -> list[dict]:
    """All rows of a tab as dicts (numbers converted back from text)."""
    data = _call(_sheets().values().get(spreadsheetId=sheet_id(), range=f"'{tab}'!A1:ZZ"))
    values = data.get("values", [])
    if not values:
        return []
    cols = values[0]
    rows = []
    for raw in values[1:]:
        row = {}
        for i, col in enumerate(cols):
            v = raw[i] if i < len(raw) else ""
            row[col] = _parse(v)
        if any(v is not None for v in row.values()):
            rows.append(row)
    return rows


def upsert_row(tab: str, header: list[str], key: str, row: dict) -> None:
    """Insert the row, or replace the existing row with the same value in column `key`."""
    try:
        existing = _call(_sheets().values().get(spreadsheetId=sheet_id(), range=f"'{tab}'!A1:ZZ")).get("values", [])
    except SheetsError as e:
        if "Unable to parse range" in str(e) or "not found" in str(e).lower():
            existing = []
        else:
            raise
    if not existing or existing[0] != header:
        _ensure_tab(tab, header)
        existing = [header] + existing[1:] if existing else [header]
    values = [["" if row.get(c) is None else row.get(c) for c in header]]
    k = header.index(key)
    for i, r in enumerate(existing[1:], start=2):
        if len(r) > k and str(r[k]) == str(row.get(key)):
            _call(_sheets().values().update(spreadsheetId=sheet_id(), range=f"'{tab}'!A{i}",
                                            valueInputOption="RAW", body={"values": values}))
            return
    _call(_sheets().values().append(spreadsheetId=sheet_id(), range=f"'{tab}'!A1", valueInputOption="RAW",
                                    insertDataOption="INSERT_ROWS", body={"values": values}))


def test_connection() -> str:
    meta = _call(_sheets().get(spreadsheetId=sheet_id(), fields="properties.title"))
    return meta.get("properties", {}).get("title", "your sheet")


def _parse(v):
    if v in ("", None):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).replace(",", "")
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return v
