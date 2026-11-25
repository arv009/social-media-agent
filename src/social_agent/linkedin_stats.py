"""LinkedIn stats from screenshots of your LinkedIn analytics page.

LinkedIn doesn't share follower counts with apps and has no export right now, so you upload a screenshot
of Profile > Analytics. Claude reads the numbers, you confirm them, and they're saved by date
(data/linkedin_stats.json) to build your follower history.
"""
import base64
import json
from datetime import date
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field

from .agent import MODEL

STATS_FILE = Path(__file__).resolve().parents[2] / "data" / "linkedin_stats.json"
FIELDS = ["total_followers", "profile_viewers", "search_appearances", "post_impressions"]


class LinkedInSnapshot(BaseModel):
    is_linkedin_analytics: bool = Field(description="True if the image shows LinkedIn analytics numbers")
    total_followers: int | None = Field(description="Total followers, e.g. 3645")
    followers_change_pct: float | None = Field(description="Change shown next to followers, e.g. 2 for ▲2%, -5 for ▼5%")
    profile_viewers: int | None
    profile_viewers_change_pct: float | None
    search_appearances: int | None
    search_appearances_period: str | None = Field(description="Date range shown for search appearances, e.g. 'Nov 10–16'")
    post_impressions: int | None
    post_impressions_change_pct: float | None
    period: str | None = Field(description="Period label shown, e.g. 'Last 7 days'")


PROMPT = ("This is a screenshot of someone's LinkedIn analytics. Read the numbers exactly as shown. "
          "Use null for anything not visible. Percent changes: positive for ▲ (green), negative for ▼ (red). "
          "Numbers like 3,645 become 3645.")


class ReadError(Exception):
    pass


def read_screenshot(image: bytes, media_type: str = "image/png") -> dict:
    """Ask Claude to read the analytics numbers from a screenshot."""
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.standard_b64encode(image).decode()}},
            {"type": "text", "text": PROMPT},
        ]}],
        output_format=LinkedInSnapshot,
    )
    if response.stop_reason == "refusal":
        raise ReadError("Claude declined to read this image.")
    snap = response.parsed_output
    if not snap or not snap.is_linkedin_analytics:
        raise ReadError("That doesn't look like a LinkedIn analytics screenshot. Upload Profile > Analytics.")
    return snap.model_dump()


# ---------- history ----------

def history() -> list[dict]:
    try:
        rows = json.loads(STATS_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return []
    return sorted(rows, key=lambda r: r["date"])


def save(entry: dict, on: date | None = None) -> None:
    """Save one day's numbers (replaces an earlier entry for the same date)."""
    day = (on or date.today()).isoformat()
    rows = [r for r in history() if r["date"] != day]
    rows.append({"date": day, **{k: v for k, v in entry.items() if k != "date"}})
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(sorted(rows, key=lambda r: r["date"]), indent=2))


def latest() -> dict | None:
    rows = [r for r in history() if r.get("total_followers") is not None]
    return rows[-1] if rows else None
