"""Upload approved graphics to Cloudinary so Buffer gets a public, permanent image link.

Free plan is enough. Settings: CLOUDINARY_URL (cloudinary://API_KEY:API_SECRET@CLOUD_NAME, shown on the
Cloudinary dashboard), or CLOUDINARY_CLOUD_NAME + CLOUDINARY_API_KEY + CLOUDINARY_API_SECRET.
Uses Cloudinary's signed upload API; the returned delivery URL (https://res.cloudinary.com/...) doesn't expire.
"""
import hashlib
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


class ImageHostError(Exception):
    pass


def _config() -> tuple[str, str, str] | None:
    url = os.getenv("CLOUDINARY_URL")
    if url:
        u = urlparse(url)
        if u.scheme == "cloudinary" and u.username and u.password and u.hostname:
            return u.hostname, u.username, u.password
    name, key, secret = (os.getenv("CLOUDINARY_CLOUD_NAME"), os.getenv("CLOUDINARY_API_KEY"),
                         os.getenv("CLOUDINARY_API_SECRET"))
    return (name, key, secret) if name and key and secret else None


def configured() -> bool:
    return _config() is not None


def upload(path: Path, folder: str = "social-media-agent") -> str:
    """Upload a local image and return its permanent HTTPS URL."""
    cfg = _config()
    if not cfg:
        raise ImageHostError("Cloudinary isn't set up. Add CLOUDINARY_URL from your Cloudinary dashboard.")
    cloud, key, secret = cfg
    params = {"folder": folder, "timestamp": str(int(time.time()))}
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params)) + secret
    params.update(api_key=key, signature=hashlib.sha1(to_sign.encode()).hexdigest())
    with open(path, "rb") as f:
        resp = requests.post(f"https://api.cloudinary.com/v1_1/{cloud}/image/upload", data=params,
                             files={"file": (Path(path).name, f)}, timeout=120)
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code >= 400 or "secure_url" not in data:
        msg = (data.get("error") or {}).get("message") or resp.text[:200]
        raise ImageHostError(f"Cloudinary upload failed: {msg}")
    return data["secure_url"]
