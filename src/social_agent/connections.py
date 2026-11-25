"""Connect accounts from the app ("Connect" buttons) with OAuth, like Claude's connectors.

Each provider needs an app/client registered with that service, whose ID and secret go in .env
(or Streamlit secrets). The redirect URL to register everywhere is the app's own URL, e.g.
  http://localhost:8501/   (local)   or   https://your-app.streamlit.app/   (Streamlit Cloud)

Tokens are saved in secrets/ (never committed). The existing connectors read them from there.
"""
import base64
import hashlib
import json
import os
import secrets as pysecrets
import time
import urllib.parse
from pathlib import Path

import requests

from . import canva_api

ROOT = Path(__file__).resolve().parents[2]
SECRETS = ROOT / "secrets"
PENDING = SECRETS / "oauth_pending.json"
META_FILE = SECRETS / "meta.json"
LINKEDIN_FILE = SECRETS / "linkedin.json"
GOOGLE_FILE = SECRETS / "google_token.json"
CANVA_FILE = canva_api.TOKEN_PATH

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v23.0")
META_SCOPES = ["pages_show_list", "pages_read_engagement", "pages_read_user_content", "read_insights",
               "pages_manage_posts", "pages_manage_engagement", "business_management", "instagram_basic",
               "instagram_manage_insights", "instagram_manage_comments", "instagram_content_publish"]
LINKEDIN_SCOPES = ["openid", "profile", "email", "w_member_social"]
GOOGLE_SCOPES = ["openid", "email", "https://www.googleapis.com/auth/drive.readonly",
                 "https://www.googleapis.com/auth/drive.file"]

PROVIDERS = {
    "meta": {"name": "Facebook & Instagram", "group": "Social accounts",
             "needs": ["META_APP_ID", "META_APP_SECRET"], "file": META_FILE,
             "what": "Live page and Instagram stats, comments, publishing approved posts.",
             "setup": "developers.facebook.com > Create app (Business) > add Facebook Login for Business; "
                      "add the app URL as a Valid OAuth Redirect URI."},
    "linkedin": {"name": "LinkedIn", "group": "Social accounts",
                 "needs": ["LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"], "file": LINKEDIN_FILE,
                 "what": "Your LinkedIn profile (posting and analytics come later).",
                 "setup": "linkedin.com/developers > Create app > Products: Sign In with LinkedIn (OpenID) and "
                          "Share on LinkedIn; add the app URL under Auth > Redirect URLs."},
    "canva": {"name": "Canva", "group": "Design & files",
              "needs": ["CANVA_CLIENT_ID", "CANVA_CLIENT_SECRET"], "file": CANVA_FILE,
              "what": "Brand templates, sending designs to Canva, exporting images.",
              "setup": "canva.com/developers > Create integration; enable the design, asset and brandtemplate "
                       "scopes; add the app URL under Authentication > Redirect URLs."},
    "google_drive": {"name": "Google Drive", "group": "Design & files",
                     "needs": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"], "file": GOOGLE_FILE,
                     "what": "Read brand docs and briefs, upload exported designs.",
                     "setup": "console.cloud.google.com > enable Google Drive API > OAuth client (Web application); "
                              "add the app URL as an Authorized redirect URI."},
}


class ConnectError(Exception):
    pass


# ---------- helpers ----------

def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def missing_config(provider: str) -> list[str]:
    return [v for v in PROVIDERS[provider]["needs"] if not os.getenv(v)]


def status(provider: str) -> dict:
    data = _load(PROVIDERS[provider]["file"])
    account = None
    if data:
        account = {"meta": lambda d: " · ".join(x for x in [d.get("page_name"), d.get("ig_username") and
                                                              "@" + d["ig_username"]] if x),
                   "linkedin": lambda d: d.get("name"),
                   "google_drive": lambda d: d.get("account"),
                   "canva": lambda d: "Canva account"}[provider](data)
    return {"connected": bool(data), "account": account, "missing": missing_config(provider)}


def disconnect(provider: str) -> None:
    PROVIDERS[provider]["file"].unlink(missing_ok=True)


def version() -> str:
    """Changes whenever an account is connected or disconnected (used to restart the agent's connectors)."""
    parts = []
    for p in PROVIDERS.values():
        f = p["file"]
        parts.append(f"{f.name}:{f.stat().st_mtime if f.exists() else 0}")
    return "|".join(parts)


def _pending() -> dict:
    data = _load(PENDING) or {}
    now = time.time()
    return {k: v for k, v in data.items() if now - v.get("created", 0) < 900}  # 15-minute window


# ---------- start sign-in ----------

def auth_url(provider: str, redirect_uri: str) -> str:
    """The URL the Connect button opens. Remembers a one-time state (and PKCE verifier for Canva)."""
    missing = missing_config(provider)
    if missing:
        raise ConnectError(f"Add {', '.join(missing)} to .env / Streamlit secrets first.")
    state = pysecrets.token_urlsafe(24)
    entry = {"provider": provider, "redirect_uri": redirect_uri, "created": time.time()}
    if provider == "meta":
        url = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?" + urllib.parse.urlencode({
            "client_id": os.environ["META_APP_ID"], "redirect_uri": redirect_uri, "state": state,
            "scope": ",".join(META_SCOPES), "response_type": "code"})
    elif provider == "linkedin":
        url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": os.environ["LINKEDIN_CLIENT_ID"], "redirect_uri": redirect_uri,
            "state": state, "scope": " ".join(LINKEDIN_SCOPES)}, quote_via=urllib.parse.quote)
    elif provider == "google_drive":
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": os.environ["GOOGLE_CLIENT_ID"], "redirect_uri": redirect_uri, "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES), "access_type": "offline", "prompt": "consent", "state": state})
    elif provider == "canva":
        verifier = pysecrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        entry["verifier"] = verifier
        url = canva_api.AUTH_URL + "?" + urllib.parse.urlencode({
            "code_challenge": challenge, "code_challenge_method": "S256", "scope": " ".join(canva_api.SCOPES),
            "response_type": "code", "client_id": os.environ["CANVA_CLIENT_ID"], "state": state,
            "redirect_uri": redirect_uri}, quote_via=urllib.parse.quote)
    else:
        raise ConnectError(f"Unknown provider {provider}")
    pending = _pending()
    pending[state] = entry
    _save(PENDING, pending)
    return url


# ---------- finish sign-in (the provider redirects back with ?code=...&state=...) ----------

def handle_callback(params: dict) -> tuple[str, str]:
    """Exchange the code for tokens and save them. Returns (provider, message)."""
    state = params.get("state")
    pending = _pending()
    entry = pending.pop(state, None) if state else None
    if not entry:
        raise ConnectError("This sign-in link expired or was already used. Click Connect again.")
    _save(PENDING, pending)
    provider = entry["provider"]
    if params.get("error"):
        raise ConnectError(f"{PROVIDERS[provider]['name']}: {params.get('error_description') or params['error']}")
    code, redirect_uri = params.get("code"), entry["redirect_uri"]
    if not code:
        raise ConnectError("No authorization code came back. Click Connect again.")
    {"meta": _finish_meta, "linkedin": _finish_linkedin, "google_drive": _finish_google,
     "canva": _finish_canva}[provider](code, redirect_uri, entry)
    return provider, f"{PROVIDERS[provider]['name']} connected."


def _check(resp: requests.Response, what: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = {"error": resp.text[:200]}
    if resp.status_code >= 400 or "error" in data:
        err = data.get("error")
        msg = err.get("message") if isinstance(err, dict) else (data.get("error_description") or err)
        raise ConnectError(f"{what} failed: {msg}")
    return data


def _finish_meta(code, redirect_uri, _entry):
    base = f"https://graph.facebook.com/{GRAPH_VERSION}"
    app = {"client_id": os.environ["META_APP_ID"], "client_secret": os.environ["META_APP_SECRET"]}
    short = _check(requests.get(f"{base}/oauth/access_token", timeout=30,
                                params={**app, "redirect_uri": redirect_uri, "code": code}), "Meta token")
    long = _check(requests.get(f"{base}/oauth/access_token", timeout=30, params={
        **app, "grant_type": "fb_exchange_token", "fb_exchange_token": short["access_token"]}), "Meta long-lived token")
    pages = _check(requests.get(f"{base}/me/accounts", timeout=30, params={
        "access_token": long["access_token"],
        "fields": "id,name,access_token,instagram_business_account{id,username}"}), "Listing Facebook Pages")
    page_list = [{"id": p["id"], "name": p["name"], "access_token": p["access_token"],
                  "ig_id": (p.get("instagram_business_account") or {}).get("id"),
                  "ig_username": (p.get("instagram_business_account") or {}).get("username")}
                 for p in pages.get("data", [])]
    if not page_list:
        raise ConnectError("No Facebook Pages found. You need admin access to a Page (and allow it during sign-in).")
    data = {"user_token": long["access_token"], "pages": page_list, "connected_at": time.time()}
    _save(META_FILE, data)
    select_meta_page(page_list[0]["id"])


def select_meta_page(page_id: str) -> None:
    """Choose which Facebook Page (and its linked Instagram account) the app works with."""
    data = _load(META_FILE)
    page = next(p for p in data["pages"] if p["id"] == page_id)
    data.update(page_id=page["id"], page_name=page["name"], page_token=page["access_token"],
                ig_user_id=page["ig_id"], ig_username=page["ig_username"])
    _save(META_FILE, data)


def meta_pages() -> list[dict]:
    data = _load(META_FILE) or {}
    return [{"id": p["id"], "name": p["name"], "ig_username": p.get("ig_username")} for p in data.get("pages", [])]


def meta_credentials() -> dict | None:
    """Page token and ids, from .env if set, otherwise from the connected account."""
    if os.getenv("META_PAGE_ACCESS_TOKEN"):
        return {"page_token": os.environ["META_PAGE_ACCESS_TOKEN"], "page_id": os.getenv("META_PAGE_ID"),
                "ig_user_id": os.getenv("META_IG_USER_ID"), "page_name": None, "ig_username": None}
    data = _load(META_FILE)
    return data if data and data.get("page_token") else None


def _finish_linkedin(code, redirect_uri, _entry):
    tok = _check(requests.post("https://www.linkedin.com/oauth/v2/accessToken", timeout=30, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": os.environ["LINKEDIN_CLIENT_ID"], "client_secret": os.environ["LINKEDIN_CLIENT_SECRET"]}),
        "LinkedIn token")
    me = _check(requests.get("https://api.linkedin.com/v2/userinfo", timeout=30,
                             headers={"Authorization": f"Bearer {tok['access_token']}"}), "LinkedIn profile")
    _save(LINKEDIN_FILE, {"access_token": tok["access_token"], "expires_at": time.time() + tok.get("expires_in", 0),
                          "name": me.get("name"), "email": me.get("email"), "sub": me.get("sub"),
                          "picture": me.get("picture")})


def linkedin_profile() -> dict | None:
    return _load(LINKEDIN_FILE)


def _finish_google(code, redirect_uri, _entry):
    tok = _check(requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "code": code, "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"], "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"}), "Google token")
    if not tok.get("refresh_token"):
        raise ConnectError("Google didn't return a refresh token. Remove the app's access at "
                           "myaccount.google.com/permissions and connect again.")
    email = None
    try:
        info = requests.get("https://openidconnect.googleapis.com/v1/userinfo", timeout=30,
                            headers={"Authorization": f"Bearer {tok['access_token']}"}).json()
        email = info.get("email")
    except (requests.RequestException, ValueError):
        pass
    # Same format google-auth's Credentials.from_authorized_user_file expects (used by the Drive connector).
    _save(GOOGLE_FILE, {"token": tok["access_token"], "refresh_token": tok["refresh_token"],
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                        "scopes": GOOGLE_SCOPES, "account": email})


def _finish_canva(code, redirect_uri, entry):
    resp = requests.post(canva_api.TOKEN_URL, headers=canva_api.basic_auth_header(), timeout=30, data={
        "grant_type": "authorization_code", "code": code, "code_verifier": entry["verifier"],
        "redirect_uri": redirect_uri})
    canva_api.save_token(_check(resp, "Canva token"))
