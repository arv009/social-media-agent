"""Shared helpers for the Streamlit pages."""
import json
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


def _export_secrets() -> None:
    """Make Streamlit Secrets available as environment variables, including keys written under a
    [section] heading (Streamlit only exports top-level keys). A [gcp_service_account] section becomes
    GOOGLE_SERVICE_ACCOUNT_JSON. Existing environment variables win."""
    try:
        secrets = st.secrets.to_dict()
    except Exception:  # noqa: BLE001 - no secrets file (e.g. running locally with .env)
        return
    for key, value in secrets.items():
        if isinstance(value, dict):
            if key.lower() in ("gcp_service_account", "google_service_account"):
                os.environ.setdefault("GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(value))
                continue
            for k2, v2 in value.items():
                if not isinstance(v2, dict):
                    os.environ.setdefault(k2.upper(), str(v2))
        else:
            os.environ.setdefault(key, str(value))


_export_secrets()

PLATFORMS = ["linkedin", "facebook", "instagram"]
PLATFORM_NAME = {"linkedin": "LinkedIn", "facebook": "Facebook", "instagram": "Instagram"}


def pname(p: str) -> str:
    return PLATFORM_NAME.get(p, p.title())


def flash(msg: str, kind: str = "success"):
    """Show a message after the next rerun (works across pages)."""
    st.session_state["flash"] = (kind, msg)


def show_flash():
    if "flash" in st.session_state:
        kind, msg = st.session_state.pop("flash")
        getattr(st, kind)(msg)


def base_url() -> str:
    """The app's own URL, used as the OAuth redirect URL. APP_URL overrides auto-detection."""
    if os.getenv("APP_URL"):
        return os.environ["APP_URL"].rstrip("/") + "/"
    headers = st.context.headers
    host = headers.get("Host", "localhost:8501")
    local = host.startswith(("localhost", "127.0.0.1"))
    proto = headers.get("X-Forwarded-Proto") or ("http" if local else "https")
    return f"{proto}://{host}/"
