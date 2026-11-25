"""Small client for the Canva Connect REST API (https://www.canva.dev/docs/apps/rest-apis/).

Login once with scripts/canva_login.py; the token is saved to secrets/canva_token.json and
refreshed automatically. Canva refresh tokens are single-use, so every refresh saves the new one.

Plan notes (from Canva's docs): brand templates and autofill need Canva Pro, Teams or Enterprise.
Uploading images, creating designs and exporting work on any plan.
"""
import base64
import json
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
TOKEN_PATH = ROOT / "secrets" / "canva_token.json"
API = "https://api.canva.com/rest/v1"
AUTH_URL = "https://www.canva.com/api/oauth/authorize"
TOKEN_URL = f"{API}/oauth/token"
SCOPES = ["design:content:read", "design:content:write", "design:meta:read", "asset:read", "asset:write",
          "brandtemplate:meta:read", "brandtemplate:content:read"]


class CanvaError(Exception):
    pass


def basic_auth_header() -> dict:
    cid, secret = os.getenv("CANVA_CLIENT_ID"), os.getenv("CANVA_CLIENT_SECRET")
    if not cid or not secret:
        raise CanvaError("Set CANVA_CLIENT_ID and CANVA_CLIENT_SECRET in .env.")
    return {"Authorization": "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()}


def save_token(data: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["expires_at"] = time.time() + int(data.get("expires_in", 14400)) - 120  # refresh 2 min early
    TOKEN_PATH.write_text(json.dumps(data, indent=2))


class CanvaClient:
    def __init__(self, session: requests.Session | None = None):
        if not TOKEN_PATH.exists():
            raise CanvaError("Not logged in to Canva. Run: python scripts/canva_login.py")
        self.http = session or requests.Session()
        self.token = json.loads(TOKEN_PATH.read_text())

    # ---------- auth ----------
    def _access_token(self) -> str:
        if time.time() >= self.token.get("expires_at", 0):
            resp = self.http.post(TOKEN_URL, headers=basic_auth_header(), timeout=30,
                                  data={"grant_type": "refresh_token", "refresh_token": self.token["refresh_token"]})
            if resp.status_code != 200:
                raise CanvaError(f"Canva token refresh failed ({resp.status_code}). "
                                 "Run python scripts/canva_login.py again.")
            save_token(resp.json())
            self.token = json.loads(TOKEN_PATH.read_text())
        return self.token["access_token"]

    def _request(self, method: str, path: str, **kw) -> dict:
        headers = {"Authorization": f"Bearer {self._access_token()}", **kw.pop("headers", {})}
        for attempt in range(4):
            resp = self.http.request(method, f"{API}{path}", headers=headers, timeout=60, **kw)
            if resp.status_code == 429 and attempt < 3:  # rate limited: back off
                time.sleep(int(resp.headers.get("Retry-After", 2 ** attempt * 5)))
                continue
            break
        if resp.status_code >= 400:
            try:
                err = resp.json()
                msg = f"{err.get('code')}: {err.get('message')}"
            except ValueError:
                msg = resp.text[:300]
            raise CanvaError(f"Canva API {resp.status_code} on {path}: {msg}")
        return resp.json()

    def _wait(self, path: str, timeout: float = 120) -> dict:
        """Poll an async job (uploads, exports, autofills) with exponential backoff."""
        delay, waited = 1.0, 0.0
        while waited < timeout:
            job = self._request("GET", path)["job"]
            if job["status"] == "success":
                return job
            if job["status"] == "failed":
                raise CanvaError(f"Canva job failed: {job.get('error', {}).get('code', 'unknown error')}")
            time.sleep(delay)
            waited += delay
            delay = min(delay * 2, 8)
        raise CanvaError(f"Canva job {path} didn't finish within {timeout:.0f}s.")

    # ---------- assets & designs ----------
    def upload_asset(self, path: Path, name: str | None = None) -> str:
        name = (name or Path(path).stem)[:50]
        meta = json.dumps({"name_base64": base64.b64encode(name.encode()).decode()})
        job = self._request("POST", "/asset-uploads", data=Path(path).read_bytes(),
                            headers={"Content-Type": "application/octet-stream", "Asset-Upload-Metadata": meta})
        return self._wait(f"/asset-uploads/{job['job']['id']}")["asset"]["id"]

    def create_design(self, title: str, width: int, height: int, asset_id: str | None = None) -> dict:
        body = {"type": "type_and_asset", "title": title[:255],
                "design_type": {"type": "custom", "width": width, "height": height}}
        if asset_id:
            body["asset_id"] = asset_id
        return self._request("POST", "/designs", json=body)["design"]

    def export_png(self, design_id: str, width: int | None = None) -> list[str]:
        fmt = {"type": "png", **({"width": width} if width else {})}
        job = self._request("POST", "/exports", json={"design_id": design_id, "format": fmt})
        return self._wait(f"/exports/{job['job']['id']}")["urls"]

    # ---------- brand templates (Canva Pro / Teams / Enterprise) ----------
    def list_brand_templates(self, query: str | None = None, limit: int = 25) -> list[dict]:
        params = {"limit": limit, **({"query": query} if query else {})}
        return self._request("GET", "/brand-templates", params=params).get("items", [])

    def template_fields(self, template_id: str) -> dict:
        return self._request("GET", f"/brand-templates/{template_id}/dataset").get("dataset", {})

    def autofill(self, template_id: str, data: dict, title: str | None = None) -> dict:
        body = {"brand_template_id": template_id, "data": data, **({"title": title[:255]} if title else {})}
        job = self._request("POST", "/autofills", json=body)
        return self._wait(f"/autofills/{job['job']['id']}")["result"]["design"]


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest
