"""Analytics connector: the ML model and post history, as tools the agent can call.

Works fully offline using data/processed/posts.csv and models/engagement_model.joblib
(created by notebooks/01_performance_model.ipynb).
"""
import json
from datetime import datetime, timedelta

import pandas as pd
from _common import ROOT, to_json
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from social_agent import model as m
from social_agent.features import TARGET, build_features, drafts_to_frame

mcp = MCPServer("analytics")
POSTS_CSV = ROOT / "data/processed/posts.csv"
MODEL_PATH = ROOT / "models/engagement_model.joblib"
_cache: dict = {}


def _posts() -> pd.DataFrame:
    mtime = POSTS_CSV.stat().st_mtime
    if _cache.get("posts_mtime") != mtime:
        _cache["posts"] = build_features(pd.read_csv(POSTS_CSV))
        _cache["posts_mtime"] = mtime
    return _cache["posts"]


def _model():
    mtime = MODEL_PATH.stat().st_mtime
    if _cache.get("model_mtime") != mtime:
        try:
            _cache["model"] = m.load(MODEL_PATH)
        except Exception as e:  # usually a scikit-learn version mismatch
            raise ToolError("Couldn't load the model (it was probably trained with a different "
                               "scikit-learn version). Re-run notebooks/01_performance_model.ipynb "
                               f"with the project's .venv. Details: {e}") from e
        _cache["model_mtime"] = mtime
    return _cache["model"]


@mcp.tool()
def performance_summary(platform: str | None = None) -> str:
    """Overall results so far: number of posts, average engagement rate and impressions per platform,
    and how many posts came from sample (fake) data versus real data.

    Args:
        platform: Optional filter: linkedin, facebook or instagram.
    """
    df = _posts()
    if platform:
        df = df[df["platform"] == platform.lower()]
    summary = df.groupby("platform").agg(posts=("post_id", "count"), avg_engagement_rate=(TARGET, "mean"),
                                         avg_impressions=("impressions", "mean"))
    return to_json({
        "by_platform": summary.round(4).reset_index().to_dict("records"),
        "data_sources": df["source"].value_counts().to_dict(),
        "date_range": [str(df["posted_at"].min()), str(df["posted_at"].max())],
    })


@mcp.tool()
def top_posts(platform: str, n: int = 5, worst: bool = False) -> str:
    """The best (or worst) past posts on a platform by engagement rate, with their text.
    Useful as examples of what to repeat or avoid.

    Args:
        platform: linkedin, facebook or instagram.
        n: How many posts to return.
        worst: True to return the lowest performers instead.
    """
    df = _posts()
    df = df[df["platform"] == platform.lower()].sort_values(TARGET, ascending=worst).head(n)
    cols = ["posted_at", "media_type", "topic", "tone", TARGET, "impressions", "text"]
    return to_json(df[cols].round(4).to_dict("records"))


@mcp.tool()
def content_insights() -> str:
    """What has worked for this account per platform (best media type, topic, tone, day, time,
    hashtag count, effect of questions, calls to action and links). Read this before writing posts."""
    return m.insights_to_prompt(m.generate_insights(_posts()))


@mcp.tool()
def score_drafts(drafts_json: str) -> str:
    """Predict the engagement rate of draft posts and rank them best first.

    Args:
        drafts_json: JSON list of drafts. Each draft needs "text", "platform", and optionally
            "media_type" (none/image/video/carousel), "posted_at" (ISO time) and "label".
            Example: [{"label": "A", "platform": "linkedin", "media_type": "carousel",
                       "posted_at": "2026-12-01T09:00", "text": "..."}]
    """
    try:
        drafts = json.loads(drafts_json)
    except json.JSONDecodeError as e:
        raise ToolError(f"drafts_json is not valid JSON ({e}).")
    default_time = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0).isoformat()
    for i, d in enumerate(drafts):
        d.setdefault("label", f"draft_{i + 1}")
        d.setdefault("media_type", "none")
        d.setdefault("posted_at", default_time)
    ranked = m.rank_drafts(_model(), drafts_to_frame(drafts))
    cols = ["label", "platform", "media_type", "topic", "tone", "day_of_week", "hour",
            "word_count", "hashtag_count", "predicted_engagement_rate"]
    return to_json(ranked[cols].round(4).to_dict("records"))


@mcp.tool()
def best_posting_times(text: str, platform: str, media_type: str = "none", top_n: int = 5) -> str:
    """Try a draft at every day and hour and return the times with the highest predicted engagement.

    Args:
        text: The post text.
        platform: linkedin, facebook or instagram.
        media_type: none, image, video or carousel.
        top_n: How many time slots to return.
    """
    row = drafts_to_frame([{"text": text, "platform": platform.lower(), "media_type": media_type,
                            "posted_at": datetime.now().isoformat()}]).iloc[0]
    slots = m.best_time_slots(_model(), row, top_n=top_n)
    return to_json(slots.round(4).to_dict("records"))


if __name__ == "__main__":
    mcp.run()
