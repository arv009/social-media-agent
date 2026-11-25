"""One-time Canva sign-in (OAuth with PKCE) for the Canva connector.

Setup in the Canva Developer Portal (https://www.canva.com/developers/integrations):
  1. Create an integration; copy the Client ID and generate a Client secret into .env as
     CANVA_CLIENT_ID and CANVA_CLIENT_SECRET.
  2. Scopes: enable design:content (read+write), design:meta (read), asset (read+write),
     brandtemplate:meta (read), brandtemplate:content (read).
  3. Authentication > Redirect URLs: add  http://127.0.0.1:3001/oauth/redirect
Then run:  python scripts/canva_login.py
"""
import base64
import hashlib
import secrets
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

import os  # noqa: E402

from social_agent.canva_api import (  # noqa: E402
    AUTH_URL, SCOPES, TOKEN_PATH, TOKEN_URL, CanvaError, basic_auth_header, save_token)

REDIRECT = os.getenv("CANVA_REDIRECT_URI", "http://127.0.0.1:3001/oauth/redirect")
result: dict = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        result.update({k: v[0] for k, v in query.items()})
        ok = "code" in query
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "Canva connected. You can close this tab." if ok else f"Canva login failed: {result}"
        self.wfile.write(f"<h2>{msg}</h2>".encode())

    def log_message(self, *args):
        pass


def main():
    try:
        basic_auth_header()  # fails early if client id/secret are missing
    except CanvaError as e:
        raise SystemExit(str(e)) from None
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "code_challenge": challenge, "code_challenge_method": "S256", "scope": " ".join(SCOPES),
        "response_type": "code", "client_id": os.environ["CANVA_CLIENT_ID"], "state": state,
        "redirect_uri": REDIRECT,
    }, quote_via=urllib.parse.quote)

    parsed = urllib.parse.urlparse(REDIRECT)
    server = HTTPServer((parsed.hostname, parsed.port), Handler)
    print("Opening Canva in your browser to approve access...\nIf it doesn't open, visit:\n" + url)
    webbrowser.open(url)
    while "code" not in result and "error" not in result:
        server.handle_request()
    if "error" in result:
        raise SystemExit(f"Canva login failed: {result}")
    if result.get("state") != state:
        raise SystemExit("Login state didn't match; please try again.")

    resp = requests.post(TOKEN_URL, headers=basic_auth_header(), timeout=30, data={
        "grant_type": "authorization_code", "code": result["code"], "code_verifier": verifier,
        "redirect_uri": REDIRECT})
    if resp.status_code != 200:
        raise SystemExit(f"Token exchange failed ({resp.status_code}): {resp.text[:300]}")
    save_token(resp.json())
    print(f"Saved {TOKEN_PATH.relative_to(ROOT)}. The Canva connector is ready.")


if __name__ == "__main__":
    main()
