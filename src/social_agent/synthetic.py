"""Generate a realistic FAKE post-performance dataset for development.

The "true" effects below (e.g. carousels and questions help, links hurt reach
on LinkedIn, LinkedIn works best Tue-Thu mornings) are baked in on purpose,
so you can check that the ML model rediscovers them. Replace this data with
your real exports / API data as soon as you have it.
"""
import numpy as np
import pandas as pd

from .schema import to_standard

TOPICS = ["tips", "promotion", "behind_the_scenes", "industry_news", "customer_story", "event"]
TONES = ["educational", "personal", "promotional", "inspirational"]

OPENERS = {
    "tips": ["3 tips to grow your small business online.", "How to write captions that convert.",
             "The biggest mistake I see in social media marketing.", "A simple checklist for your next campaign."],
    "promotion": ["Our new product is available now.", "Big sale this week: 20% off all plans.",
                  "We just launched something new.", "Limited offer for our community."],
    "behind_the_scenes": ["Behind the scenes at our office today.", "Meet our team: the people behind the posts.",
                          "A day in the life of our design team.", "Here's what our workspace looks like on a busy Monday."],
    "industry_news": ["New report: social media trends for next year.", "The algorithm update everyone is talking about.",
                      "Industry news: data shows video is still growing.", "A new study on how people shop online."],
    "customer_story": ["Customer success story: how Maria doubled her sales.", "A client review that made our week.",
                       "Case study: from 0 to 5,000 followers.", "Our customer shared their results with us."],
    "event": ["Join us for a free webinar next Thursday.", "Our workshop is open for registration.",
              "We're going live tomorrow at 7 PM.", "See you at the marketing conference this weekend."],
}
TONE_LINES = {
    "educational": ["Here's what works, step by step.", "Let's break it down.", "Save these for later."],
    "personal": ["Honestly, I was skeptical at first.", "I've made this mistake myself.", "My confession: I almost gave up."],
    "promotional": ["Shop now while the offer lasts.", "Limited spots, don't miss it.", "Buy today and get a free bonus."],
    "inspirational": ["Never give up on the journey.", "Grateful for this community.", "Believe in the process and keep going."],
}
FILLER = ["Consistency beats perfection.", "Small steps add up over time.", "Your audience wants value, not noise.",
          "Test, measure, and improve.", "Good content starts with knowing who you're talking to.",
          "Every brand has a story worth telling.", "Focus on one platform before adding more."]
QUESTIONS = ["What would you add?", "Have you tried this?", "Which one is your favorite?", "Agree or disagree?"]
CTAS = ["Comment below and share with a friend.", "Follow for more tips.", "Link in bio to learn more.",
        "Register now.", "Save this post."]
HASHTAGS = ["#marketing", "#smallbusiness", "#socialmedia", "#branding", "#entrepreneur",
            "#contentmarketing", "#growth", "#digitalmarketing", "#startup", "#business"]
EMOJIS = ["🚀", "✨", "💡", "🔥", "👇", "🙌", "📈"]

PLATFORM_BASE_RATE = {"linkedin": 0.035, "facebook": 0.020, "instagram": 0.045}
PLATFORM_IMPRESSIONS = {"linkedin": 1500, "facebook": 900, "instagram": 2000}
PLATFORM_MEDIA = {
    "linkedin": (["none", "image", "video", "carousel"], [0.30, 0.40, 0.15, 0.15]),
    "facebook": (["none", "image", "video", "carousel"], [0.25, 0.45, 0.20, 0.10]),
    "instagram": (["image", "video", "carousel"], [0.45, 0.30, 0.25]),
}
MEDIA_EFFECT = {"none": 0.80, "image": 1.10, "video": 1.30, "carousel": 1.45}
TOPIC_EFFECT = {"tips": 1.25, "promotion": 0.70, "behind_the_scenes": 1.10,
                "industry_news": 1.00, "customer_story": 1.15, "event": 0.85}
TONE_EFFECT = {"educational": 1.00, "personal": 1.20, "promotional": 0.75, "inspirational": 1.05}


def _timing_effect(platform: str, ts: pd.Timestamp) -> float:
    dow, hour = ts.dayofweek, ts.hour
    if platform == "linkedin":
        if dow >= 5:
            return 0.70
        if dow in (1, 2, 3) and 7 <= hour <= 10:
            return 1.25
        return 1.0 if 7 <= hour <= 17 else 0.85
    if platform == "facebook":
        return 1.10 if (11 <= hour <= 13 or 18 <= hour <= 21) else 0.95
    # instagram
    eff = 1.25 if 18 <= hour <= 22 else (0.80 if hour < 8 else 1.0)
    return eff * (1.05 if dow >= 5 else 1.0)


def _hashtag_effect(platform: str, n: int) -> float:
    best = 3 if platform == "linkedin" else 5
    return 1 + 0.05 * min(n, best) - 0.06 * max(n - best, 0)


def _length_effect(platform: str, words: int) -> float:
    if platform == "linkedin":
        return 1.15 if 60 <= words <= 200 else 0.9
    return 1.10 if words <= 50 else 0.92


def _random_timestamp(rng, start, days, platform) -> pd.Timestamp:
    day = start + pd.Timedelta(days=int(rng.integers(0, days)))
    hour_probs = np.ones(24)
    hour_probs[:6] = 0.05
    hour_probs[6:23] = 1.0
    hour_probs /= hour_probs.sum()
    hour = int(rng.choice(24, p=hour_probs))
    return day + pd.Timedelta(hours=hour, minutes=int(rng.integers(0, 60)))


def generate(n_posts: int = 450, seed: int = 42, end: str = "2026-11-20", days: int = 540) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start = pd.Timestamp(end) - pd.Timedelta(days=days)
    rows = []
    for i in range(n_posts):
        platform = rng.choice(["linkedin", "facebook", "instagram"], p=[0.45, 0.25, 0.30])
        media_opts, media_p = PLATFORM_MEDIA[platform]
        media = rng.choice(media_opts, p=media_p)
        topic = rng.choice(TOPICS, p=[0.28, 0.15, 0.15, 0.14, 0.14, 0.14])
        tone = rng.choice(TONES, p=[0.40, 0.25, 0.15, 0.20])
        if topic == "promotion" and rng.random() < 0.6:
            tone = "promotional"
        ts = _random_timestamp(rng, start, days, platform)

        has_question = rng.random() < 0.35
        has_cta = rng.random() < 0.45
        has_link = platform != "instagram" and rng.random() < 0.30
        n_hashtags = int(rng.integers(0, 4 if platform == "linkedin" else 12))
        n_emoji = int(rng.integers(0, 4))
        n_filler = int(rng.integers(0, 3 if platform == "instagram" else 12))

        parts = [rng.choice(OPENERS[topic]), rng.choice(TONE_LINES[tone])]
        parts += list(rng.choice(FILLER, size=n_filler, replace=True))
        if has_question:
            parts.append(rng.choice(QUESTIONS))
        if has_cta:
            parts.append(rng.choice(CTAS))
        if has_link:
            parts.append("https://example.com/blog")
        text = " ".join(parts)
        if n_emoji:
            text = " ".join(rng.choice(EMOJIS, size=n_emoji)) + " " + text
        if n_hashtags:
            text += "\n\n" + " ".join(rng.choice(HASHTAGS, size=min(n_hashtags, len(HASHTAGS)), replace=False))
        words = len(text.split())

        rate = PLATFORM_BASE_RATE[platform]
        rate *= MEDIA_EFFECT[media] * TOPIC_EFFECT[topic] * TONE_EFFECT[tone]
        if platform == "linkedin" and tone == "personal":
            rate *= 1.12
        if platform == "instagram" and topic == "behind_the_scenes":
            rate *= 1.18
        rate *= 1.15 if has_question else 1.0
        rate *= 1.08 if has_cta else 1.0
        if has_link:
            rate *= 0.75 if platform == "linkedin" else 0.90
        rate *= _timing_effect(platform, ts) * _hashtag_effect(platform, n_hashtags) * _length_effect(platform, words)
        rate *= rng.lognormal(0, 0.30)  # everything we can't measure
        rate = float(np.clip(rate, 0.001, 0.4))

        growth = 1 + 0.6 * (ts - start).days / days  # audience grows over time
        reach_boost = 1.3 if media == "video" else 1.0
        if has_link and platform == "linkedin":
            reach_boost *= 0.7
        impressions = int(PLATFORM_IMPRESSIONS[platform] * growth * reach_boost * rng.lognormal(0, 0.5))
        impressions = max(impressions, 50)

        total = rng.binomial(impressions, rate)
        if platform == "instagram":
            split = [0.70, 0.10, 0.07, 0.03, 0.10]  # likes, comments, shares, clicks, saves
        else:
            split = [0.62, 0.12, 0.08, 0.18 if has_link else 0.10, 0.0]
        split = np.array(split) / sum(split)
        likes, comments, shares, clicks, saves = rng.multinomial(total, split)

        rows.append({
            "post_id": f"sample_{i:04d}",
            "platform": platform,
            "posted_at": ts,
            "text": text,
            "media_type": media,
            "impressions": impressions,
            "reach": int(impressions * rng.uniform(0.6, 0.9)),
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "clicks": clicks,
            "saves": saves if platform == "instagram" else np.nan,
            "source": "sample",
        })
    return to_standard(pd.DataFrame(rows), source="sample").sort_values("posted_at").reset_index(drop=True)
