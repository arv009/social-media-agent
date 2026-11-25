"""Turn standard post rows into model features.

Topic and tone come from simple keyword rules for now. In a later stage an
LLM can label them instead (more accurate); the rest of the code won't change.
"""
import re

import numpy as np
import pandas as pd

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")
HASHTAG_RE = re.compile(r"#\w+")
MENTION_RE = re.compile(r"@\w+")
LINK_RE = re.compile(r"https?://\S+|www\.\S+")

CTA_WORDS = ["comment", "share", "follow", "link in bio", "sign up", "register", "dm us",
             "book", "shop", "download", "learn more", "click", "tag a", "join us", "save this"]

TOPIC_KEYWORDS = {
    "tips": ["tip", "how to", "mistake", "guide", "step by step", "lesson", "hack", "checklist"],
    "promotion": ["sale", "discount", "% off", "launch", "new product", "offer", "promo", "available now", "shop"],
    "behind_the_scenes": ["behind the scenes", "our team", "meet", "office", "day in the life", "workspace"],
    "industry_news": ["report", "trend", "update", "news", "study", "algorithm", "industry", "data shows"],
    "customer_story": ["customer", "client", "testimonial", "success story", "case study", "review"],
    "event": ["webinar", "event", "workshop", "live", "join us", "register", "conference"],
}

TONE_KEYWORDS = {
    "personal": [" i ", "i've", "i was", "my ", "me ", "honestly", "confession"],
    "promotional": ["sale", "% off", "buy", "shop", "limited", "offer", "discount", "available now"],
    "inspirational": ["dream", "never give up", "believe", "grateful", "journey", "inspire", "proud"],
}

CATEGORICAL_FEATURES = ["platform", "media_type", "topic", "tone", "day_of_week", "time_of_day"]
NUMERIC_FEATURES = ["hour", "is_weekend", "word_count", "hashtag_count", "emoji_count",
                    "mention_count", "has_question", "has_link", "has_cta"]
FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES
TARGET = "engagement_rate"

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _first_match(text: str, keyword_map: dict, default: str) -> str:
    t = f" {text.lower()} "
    scores = {label: sum(kw in t for kw in kws) for label, kws in keyword_map.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else default


def tag_topic(text: str) -> str:
    return _first_match(text, TOPIC_KEYWORDS, "general")


def tag_tone(text: str) -> str:
    return _first_match(text, TONE_KEYWORDS, "educational")


def time_of_day(hour: int) -> str:
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 14:
        return "midday"
    if 14 <= hour < 18:
        return "afternoon"
    return "evening"


def text_features(text: str) -> dict:
    lower = text.lower()
    return {
        "word_count": len(text.split()),
        "hashtag_count": len(HASHTAG_RE.findall(text)),
        "emoji_count": len(EMOJI_RE.findall(text)),
        "mention_count": len(MENTION_RE.findall(text)),
        "has_question": int("?" in text),
        "has_link": int(bool(LINK_RE.search(text))),
        "has_cta": int(any(w in lower for w in CTA_WORDS)),
        "topic": tag_topic(text),
        "tone": tag_tone(text),
    }


def engagement_rate(df: pd.DataFrame) -> pd.Series:
    """(likes + comments + shares + clicks + saves) / impressions. Missing metrics count as 0."""
    interactions = df[["likes", "comments", "shares", "clicks", "saves"]].fillna(0).sum(axis=1)
    impressions = df["impressions"].where(df["impressions"] > 0)
    return interactions / impressions


def build_features(df: pd.DataFrame, with_target: bool = True) -> pd.DataFrame:
    """Add feature columns (and the target) to a standard-schema DataFrame."""
    out = df.copy()
    ts = pd.to_datetime(out["posted_at"])
    out["hour"] = ts.dt.hour
    out["day_of_week"] = ts.dt.dayofweek.map(dict(enumerate(DAYS)))
    out["is_weekend"] = (ts.dt.dayofweek >= 5).astype(int)
    out["time_of_day"] = out["hour"].apply(time_of_day)

    tf = out["text"].fillna("").apply(text_features).apply(pd.Series)
    out[tf.columns] = tf

    if with_target:
        out[TARGET] = engagement_rate(out)
        out = out[out[TARGET].notna() & np.isfinite(out[TARGET])]
    return out


def drafts_to_frame(drafts: list[dict]) -> pd.DataFrame:
    """Turn draft posts (text, platform, media_type, posted_at) into a feature frame for scoring."""
    df = pd.DataFrame(drafts)
    df["media_type"] = df.get("media_type", "none")
    return build_features(df, with_target=False)
