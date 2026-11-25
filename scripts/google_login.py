"""One-time Google sign-in for the Google Drive connector.

Save your OAuth client file (Desktop app) as secrets/google_credentials.json, then run:
    python scripts/google_login.py
A browser window opens; after you allow access, secrets/google_token.json is saved.
"""
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/drive.file"]
CREDS = ROOT / "secrets/google_credentials.json"
TOKEN = ROOT / "secrets/google_token.json"

if not CREDS.exists():
    raise SystemExit(f"Missing {CREDS.relative_to(ROOT)}. Download it from Google Cloud Console "
                     "(APIs & Services > Credentials > OAuth client ID > Desktop app).")
creds = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES).run_local_server(port=0)
TOKEN.write_text(creds.to_json())
print(f"Saved {TOKEN.relative_to(ROOT)}. The Google Drive connector is ready.")
