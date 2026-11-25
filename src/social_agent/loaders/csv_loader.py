"""Load analytics CSV/Excel exports (LinkedIn, Meta Business Suite, Buffer, ...).

Every platform names its columns differently, and the names change over time.
COLUMN_ALIASES maps the common ones to our standard columns. If your export
uses a name that isn't listed, add it here (lowercase) or pass `column_map`.
"""
from pathlib import Path

import pandas as pd

from ..schema import to_standard

COLUMN_ALIASES = {
    "post_id": ["post id", "post_id", "id", "update id", "media id", "permalink", "post link", "url"],
    "platform": ["platform", "network", "channel", "service"],
    "posted_at": ["posted_at", "created date", "publish time", "published", "date", "created time",
                  "posted", "post date", "sent at", "timestamp"],
    "text": ["text", "post title", "update title", "message", "caption", "content", "description",
             "post text", "post commentary", "title"],
    "media_type": ["media_type", "post type", "content type", "media type", "type"],
    "impressions": ["impressions", "views", "impressions (organic)", "post impressions"],
    "reach": ["reach", "unique impressions", "people reached", "accounts reached"],
    "likes": ["likes", "reactions", "reactions, comments and shares", "post reactions"],
    "comments": ["comments", "post comments"],
    "shares": ["shares", "reposts", "post shares"],
    "clicks": ["clicks", "link clicks", "clicks (organic)", "post clicks"],
    "saves": ["saves", "saved"],
}


def _auto_map(columns) -> dict:
    lookup = {c.lower().strip(): c for c in columns}
    mapping = {}
    for std, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lookup and lookup[alias] not in mapping:
                mapping[lookup[alias]] = std
                break
    return mapping


def load_csv(path, platform: str | None = None, column_map: dict | None = None) -> pd.DataFrame:
    """Read one export file and return it in the standard schema.

    platform: set this when the file has no platform column (e.g. a LinkedIn export).
    column_map: {"Their Column Name": "standard_name"} to override the auto-mapping.
    """
    path = Path(path)
    df = pd.read_excel(path) if path.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(path)
    mapping = _auto_map(df.columns)
    mapping.update(column_map or {})
    df = df.rename(columns=mapping)
    df = df.loc[:, ~df.columns.duplicated()]
    if platform:
        df["platform"] = platform
    if "platform" not in df.columns:
        raise ValueError(f"{path.name}: no platform column found. Pass platform='linkedin' (or similar).")
    if "post_id" not in df.columns:
        df["post_id"] = [f"{path.stem}_{i}" for i in range(len(df))]
    missing = [c for c in ("posted_at", "impressions") if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: couldn't find {missing}. Columns are {list(df.columns)}. "
                         "Pass column_map={...} to say which column is which.")
    return to_standard(df, source=f"csv:{path.name}")


def load_folder(folder, platform_from_name: bool = True) -> pd.DataFrame:
    """Load every CSV/XLSX in a folder. If a file name contains 'linkedin',
    'facebook' or 'instagram', that's used as its platform."""
    frames = []
    for path in sorted(Path(folder).glob("*")):
        if path.suffix.lower() not in (".csv", ".xlsx", ".xls"):
            continue
        platform = None
        if platform_from_name:
            for p in ("linkedin", "facebook", "instagram"):
                if p in path.name.lower():
                    platform = p
        frames.append(load_csv(path, platform=platform))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
