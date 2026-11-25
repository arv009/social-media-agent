"""Dashboard: live numbers from Buffer (or Facebook & Instagram directly); sample data until you connect."""
import os
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from ui import PLATFORM_ICON, ROOT, flash, pname, show_flash

from social_agent import buffer_api
from social_agent import connections as cx
from social_agent.features import TARGET, build_features
from social_agent.schema import combine

POSTS_CSV = ROOT / "data/processed/posts.csv"


@st.cache_data(ttl=600, show_spinner="Loading live data from Facebook & Instagram…")
def load_live(version: str) -> dict:
    """Account info + recent posts from Meta. Cached 10 minutes (per connection state)."""
    from social_agent.loaders.meta_api import MetaClient

    client = MetaClient()
    out = {"accounts": [], "posts": pd.DataFrame(), "errors": []}
    if client.page_id:
        try:
            info = client.page_info()
            out["accounts"].append({"platform": "facebook", "name": info.get("name"),
                                    "followers": info.get("followers_count") or info.get("fan_count"),
                                    "link": info.get("link")})
        except Exception as e:  # noqa: BLE001 - show what failed, keep the rest of the dashboard
            out["errors"].append(f"Facebook Page: {e}")
    if client.ig_user_id:
        try:
            info = client.instagram_info()
            out["accounts"].append({"platform": "instagram", "name": "@" + info.get("username", ""),
                                    "followers": info.get("followers_count"), "posts": info.get("media_count"),
                                    "link": f"https://instagram.com/{info.get('username', '')}"})
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"Instagram: {e}")
    try:
        out["posts"] = client.fetch_all(max_posts=50)
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"Posts: {e}")
    if client.skipped_metrics:
        out["errors"].append("Meta no longer provides these metrics: " + ", ".join(sorted(client.skipped_metrics)))
    return out


@st.cache_data(ttl=900, show_spinner="Loading posts and analytics from Buffer…")
def load_buffer(_key_hint: str) -> dict:
    """Channels + published posts with metrics from Buffer. Cached 15 minutes (Buffer refreshes metrics daily)."""
    out = {"accounts": [], "posts": pd.DataFrame(), "errors": []}
    try:
        client = buffer_api.BufferClient()
        for c in client.channels():
            if c["service"].lower() in PLATFORM_ICON:
                out["accounts"].append({"platform": c["service"].lower(),
                                        "name": c.get("displayName") or c.get("name"), "followers": None})
        out["posts"] = client.sent_posts_frame(limit=150)
    except buffer_api.BufferError as e:
        out["errors"].append(str(e))
    return out


@st.cache_data(ttl=300)
def load_sample(mtime: float) -> pd.DataFrame:
    df = pd.read_csv(POSTS_CSV)
    return df[df["source"] == "sample"]


def interactions(df: pd.DataFrame) -> pd.Series:
    return df[["likes", "comments", "shares", "clicks", "saves"]].fillna(0).sum(axis=1)


def render_posts(df: pd.DataFrame, accounts: list[dict], live: bool):
    df = df.copy()
    df["posted_at"] = pd.to_datetime(df["posted_at"])
    df["interactions"] = interactions(df)
    feats = build_features(df) if df["impressions"].notna().any() else df.assign(**{TARGET: float("nan")})
    df[TARGET] = feats[TARGET] if TARGET in feats else float("nan")

    end = df["posted_at"].max() if not live else pd.Timestamp(datetime.now())
    last30 = df[df["posted_at"] >= end - timedelta(days=30)]
    prev30 = df[(df["posted_at"] < end - timedelta(days=30)) & (df["posted_at"] >= end - timedelta(days=60))]

    def delta(cur, prev):
        return None if not prev else f"{(cur - prev) / prev:+.0%} vs previous 30 days"

    k = st.columns(5)
    known = [a["followers"] for a in accounts if a.get("followers") is not None]
    k[0].metric("Followers", f"{sum(known):,}" if known else "–",
                help="Facebook Page + Instagram followers (needs the direct Facebook & Instagram connection)")
    k[1].metric("Posts (30 days)", len(last30), delta(len(last30), len(prev30)))
    k[2].metric("Interactions (30 days)", f"{int(last30['interactions'].sum()):,}",
                delta(last30["interactions"].sum(), prev30["interactions"].sum()))
    imp = last30["impressions"].sum()
    k[3].metric("Impressions / views (30 days)", f"{int(imp):,}" if imp else "–")
    er = last30[TARGET].mean()
    k[4].metric("Avg engagement rate", f"{er:.2%}" if pd.notna(er) else "–",
                help="(likes + comments + shares + clicks + saves) / impressions")

    if accounts:
        cols = st.columns(len(accounts))
        for col, a in zip(cols, accounts):
            with col.container(border=True):
                st.markdown(f"**{PLATFORM_ICON.get(a['platform'], '')} {a['name']}**")
                extra = f" · {a['posts']:,} posts" if a.get("posts") else ""
                if a.get("followers") is not None:
                    st.caption(f"{a['followers']:,} followers{extra}")
                else:
                    st.caption(f"{pname(a['platform'])} via Buffer")
                if a.get("link"):
                    st.link_button("Open", a["link"])

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Interactions per week**")
        weekly = (df.set_index("posted_at").groupby("platform")["interactions"].resample("W").sum()
                  .unstack(0).fillna(0).tail(26))
        st.area_chart(weekly.rename(columns=pname))
    with right:
        st.markdown("**Average interactions by format**")
        by_media = df.pivot_table(index="media_type", columns="platform", values="interactions", aggfunc="mean")
        st.bar_chart(by_media.rename(columns=pname), stack=False)

    st.markdown("**Recent posts**")
    table = df.sort_values("posted_at", ascending=False).head(25)
    table = table.assign(platform=table["platform"].map(lambda p: f"{PLATFORM_ICON.get(p, '')} {pname(p)}"),
                         text=table["text"].str.slice(0, 140))
    st.dataframe(table[["posted_at", "platform", "media_type", "text", "impressions", "likes", "comments",
                        "shares", "interactions", TARGET]],
                 hide_index=True, use_container_width=True,
                 column_config={"posted_at": st.column_config.DatetimeColumn("Posted", format="MMM D, YYYY"),
                                TARGET: st.column_config.NumberColumn("Engagement rate", format="percent"),
                                "text": st.column_config.TextColumn("Post", width="large")})


st.title("📊 Dashboard")
show_flash()
creds = cx.meta_credentials()
source = "buffer" if buffer_api.configured() else ("meta" if creds else None)

if source:
    if source == "buffer":
        data = load_buffer(os.environ["BUFFER_API_KEY"][-6:])
        note = "Live from Buffer · Buffer updates post metrics about once a day"
        loader = load_buffer
    else:
        data = load_live(cx.version())
        note = "Live from Facebook & Instagram · refreshed at most every 10 minutes"
        loader = load_live
    c1, c2, c3 = st.columns([2, 1, 1])
    c1.caption(f"{note} · {datetime.now():%I:%M %p}")
    if c2.button("🔄 Refresh now", use_container_width=True):
        loader.clear()
        st.rerun()
    if c3.button("💾 Save to ML dataset", use_container_width=True, disabled=data["posts"].empty,
                 help="Adds these posts to data/processed/posts.csv so the model learns from your real results."):
        existing = pd.read_csv(POSTS_CSV) if POSTS_CSV.exists() else data["posts"].iloc[0:0]
        combine(existing, data["posts"]).to_csv(POSTS_CSV, index=False)
        flash(f"Saved {len(data['posts'])} posts to the dataset. Retrain the model in the notebook to use them.")
        st.rerun()
    for err in data["errors"]:
        st.warning(err)
    if data["posts"].empty:
        st.info("Connected, but no posts came back yet.")
    else:
        render_posts(data["posts"], data["accounts"], live=True)
else:
    st.warning("Showing **sample (fake) data**. Connect Buffer (or Facebook & Instagram) to see your live numbers.")
    st.page_link("views/connections.py", label="Go to Connections", icon="🔌")
    if POSTS_CSV.exists():
        render_posts(load_sample(POSTS_CSV.stat().st_mtime), [], live=False)

profile = cx.linkedin_profile()
if profile:
    st.caption(f"💼 LinkedIn connected as {profile.get('name')}. LinkedIn stats need API approval, so they "
               "aren't shown here yet.")
