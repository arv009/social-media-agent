"""Shared helpers for the Streamlit pages."""
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

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
