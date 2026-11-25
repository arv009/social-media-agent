"""Shared setup for every connector server: import paths and .env loading.

Connector servers talk to the agent over stdin/stdout (MCP stdio transport),
so they must never print() to stdout. Log to stderr instead.
"""
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(name)s: %(message)s")


def to_json(obj) -> str:
    """Tool results are text; JSON keeps them easy for the model to read."""
    return json.dumps(obj, indent=2, default=str)
