"""The one standard table every data source is converted into.

CSV exports, the Meta API, LinkedIn, Buffer... each loader outputs these
columns, so the feature and model code never cares where data came from.
"""
import pandas as pd

STANDARD_COLUMNS = [
    "post_id",      # unique id from the platform
    "platform",     # linkedin | facebook | instagram
    "posted_at",    # timestamp (timezone-naive local time)
    "text",         # caption / post body
    "media_type",   # none | image | video | carousel
    "impressions",  # times shown (Meta "views" also maps here)
    "reach",        # unique people reached (may be missing)
    "likes",        # likes / reactions
    "comments",
    "shares",
    "clicks",       # link or post clicks (may be missing)
    "saves",        # Instagram saves (may be missing)
    "source",       # where the row came from: sample | csv | meta_api | ...
]

METRIC_COLUMNS = ["impressions", "reach", "likes", "comments", "shares", "clicks", "saves"]
PLATFORMS = ["linkedin", "facebook", "instagram"]
MEDIA_TYPES = ["none", "image", "video", "carousel"]


def to_standard(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Add any missing standard columns, fix types and keep only the standard set."""
    out = df.copy()
    for col in STANDARD_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    out["source"] = out["source"].fillna(source)
    out["posted_at"] = pd.to_datetime(out["posted_at"], errors="coerce", utc=True).dt.tz_localize(None)
    out["platform"] = out["platform"].astype(str).str.lower().str.strip()
    out["media_type"] = out["media_type"].fillna("none").astype(str).str.lower().str.strip()
    out["media_type"] = out["media_type"].replace(
        {"photo": "image", "carousel_album": "carousel", "album": "carousel",
         "reels": "video", "reel": "video", "text": "none", "status": "none", "link": "none", "nan": "none"}
    )
    out["text"] = out["text"].fillna("").astype(str)
    for col in METRIC_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["post_id"] = out["post_id"].astype(str)
    return out[STANDARD_COLUMNS]


def combine(*frames: pd.DataFrame) -> pd.DataFrame:
    """Stack data from several sources, dropping duplicate posts (latest row wins)."""
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["platform", "post_id"], keep="last")
    return df.sort_values("posted_at").reset_index(drop=True)
