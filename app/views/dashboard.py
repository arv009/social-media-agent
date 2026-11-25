"""Dashboard: live numbers from Buffer (or Facebook & Instagram directly); sample data until you connect.

Followers: Facebook and Instagram counts come from the direct Facebook & Instagram connection (Buffer doesn't
provide them). LinkedIn doesn't share follower counts through its API, so you enter that number yourself.
"""
import os
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st
from ui import PLATFORMS, ROOT, flash, pname, show_flash

import anthropic

from social_agent import buffer_api, linkedin_stats, sheets_store
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
    meta_accounts(client, out)
    try:
        out["posts"] = client.fetch_all(max_posts=50)
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"Posts: {e}")
    if client.skipped_metrics:
        out["errors"].append("Meta no longer provides these metrics: " + ", ".join(sorted(client.skipped_metrics)))
    return out


@st.cache_data(ttl=600, show_spinner="Loading follower counts from Facebook & Instagram…")
def load_meta_accounts(version: str) -> dict:
    """Only the Facebook Page and Instagram account info (followers), used alongside Buffer data."""
    from social_agent.loaders.meta_api import MetaClient

    out = {"accounts": [], "errors": []}
    try:
        meta_accounts(MetaClient(), out)
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"Facebook & Instagram: {e}")
    return out


def meta_accounts(client, out: dict) -> None:
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


def linkedin_followers() -> dict | None:
    """Latest LinkedIn numbers: from your screenshot uploads, else LINKEDIN_FOLLOWERS in Secrets."""
    last = linkedin_stats.latest()
    if last:
        return {"count": last["total_followers"], "as_of": last["date"],
                "profile_viewers": last.get("profile_viewers"), "post_impressions": last.get("post_impressions")}
    env = os.getenv("LINKEDIN_FOLLOWERS", "").replace(",", "").strip()
    return {"count": int(env), "as_of": None} if env.isdigit() else None


def merge_accounts(base: list[dict], meta: list[dict]) -> list[dict]:
    """Add Facebook/Instagram follower counts from Meta and your LinkedIn count to the account list."""
    accounts = [dict(a) for a in base]
    for m in meta:
        match = next((a for a in accounts if a["platform"] == m["platform"]), None)
        if match:
            match.update({k: v for k, v in m.items() if v is not None and k != "name"})
        else:
            accounts.append(dict(m))
    li = linkedin_followers()
    if li:
        match = next((a for a in accounts if a["platform"] == "linkedin"), None)
        if not match:
            match = {"platform": "linkedin", "name": "LinkedIn"}
            accounts.append(match)
        match.update(followers=li["count"], manual=True, as_of=li.get("as_of"),
                     profile_viewers=li.get("profile_viewers"), post_impressions=li.get("post_impressions"))
    order = {p: i for i, p in enumerate(PLATFORMS)}
    return sorted(accounts, key=lambda a: order.get(a["platform"], 9))


@st.cache_data(ttl=900, show_spinner="Loading posts and analytics from Buffer…")
def load_buffer(_key_hint: str) -> dict:
    """Channels + published posts with metrics from Buffer. Cached 15 minutes (Buffer refreshes metrics daily)."""
    out = {"accounts": [], "posts": pd.DataFrame(), "errors": []}
    try:
        client = buffer_api.BufferClient()
        for c in client.channels():
            if c["service"].lower() in PLATFORMS:
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


def render_accounts(accounts: list[dict]):
    if not accounts:
        return
    known = [a["followers"] for a in accounts if a.get("followers") is not None]
    st.markdown(f"**Followers: {sum(known):,}**" if known else "**Followers**")
    cols = st.columns(len(accounts))
    for col, a in zip(cols, accounts):
        with col.container(border=True):
            st.caption(pname(a["platform"]))
            if a["name"] != pname(a["platform"]):
                st.markdown(f"**{a['name']}**")
            if a.get("followers") is not None:
                extra = f" · {a['posts']:,} posts" if a.get("posts") else ""
                st.markdown(f"### {a['followers']:,}")
                note = f"as of {a['as_of']}" if a.get("manual") and a.get("as_of") else (
                    "entered by you" if a.get("manual") else "live")
                st.caption(f"followers{extra} · {note}")
                if a.get("profile_viewers") is not None or a.get("post_impressions") is not None:
                    st.caption(f"Last 7 days: {a.get('profile_viewers') or 0} profile viewers · "
                               f"{a.get('post_impressions') or 0:,} post impressions")
            elif a["platform"] == "linkedin":
                st.caption("Upload a LinkedIn analytics screenshot below")
            else:
                st.caption("Connect Facebook & Instagram on the Connections page to see followers")
            if a.get("link"):
                st.link_button("Open", a["link"])


def linkedin_editor():
    """Upload a screenshot of LinkedIn > Analytics; Claude reads the numbers; you confirm and save."""
    with st.expander("Update LinkedIn stats from a screenshot"):
        st.caption("LinkedIn doesn't share stats with apps, so take a screenshot of your LinkedIn **Analytics** "
                   "(Profile > Analytics: Total followers, Profile viewers, Search appearances, Post impressions) "
                   "and upload it here. Do it as often as you like to build your follower history.")
        shot = st.file_uploader("LinkedIn analytics screenshot", type=["png", "jpg", "jpeg", "webp"],
                                key="li_shot")
        if shot is not None and st.button("Read the numbers", type="primary", disabled=not os.getenv("ANTHROPIC_API_KEY"),
                                          help=None if os.getenv("ANTHROPIC_API_KEY") else "Needs ANTHROPIC_API_KEY"):
            with st.spinner("Reading the screenshot…"):
                try:
                    st.session_state.li_read = linkedin_stats.read_screenshot(shot.getvalue(), shot.type or "image/png")
                except linkedin_stats.ReadError as e:
                    st.error(str(e))
                except anthropic.APIError as e:
                    st.error(f"Couldn't read the image: {e}")
        found = st.session_state.get("li_read") or {}
        if found:
            st.success("Check the numbers below, fix anything that's off, then save.")
        with st.form("li_form", clear_on_submit=False):
            c = st.columns(4)
            vals = {}
            for col, (key, label) in zip(c, [("total_followers", "Total followers"), ("profile_viewers", "Profile viewers"),
                                             ("search_appearances", "Search appearances"),
                                             ("post_impressions", "Post impressions")]):
                vals[key] = col.number_input(label, min_value=0, step=1, value=int(found.get(key) or 0),
                                             key=f"li_{key}_{found.get(key)}")
            day = st.date_input("Date of these numbers", date.today())
            if st.form_submit_button("Save", type="primary"):
                if not vals["total_followers"]:
                    st.error("Total followers is required.")
                else:
                    extra = {k: found.get(k) for k in found if k.endswith("_pct") or k.endswith("period")}
                    try:
                        linkedin_stats.save({**vals, **extra}, on=day)
                    except sheets_store.SheetsError as e:
                        st.error(f"Couldn't save to the Google Sheet: {e}")
                    else:
                        st.session_state.pop("li_read", None)
                        flash(f"LinkedIn stats saved for {day:%b %d} ({linkedin_stats.storage()}).")
                        st.rerun()
        try:
            rows = linkedin_stats.history()
        except sheets_store.SheetsError as e:
            st.warning(f"Couldn't read the Google Sheet: {e}")
            rows = []
        if rows:
            hist = pd.DataFrame(rows)
            hist["date"] = pd.to_datetime(hist["date"])
            if len(hist) >= 2:
                import altair as alt

                st.markdown("**LinkedIn followers over time**")
                chart = alt.Chart(hist).mark_line(point=True).encode(
                    x=alt.X("date:T", title=None),
                    y=alt.Y("total_followers:Q", title="Followers", scale=alt.Scale(zero=False)),
                    tooltip=[alt.Tooltip("date:T", format="%b %d, %Y"), alt.Tooltip("total_followers:Q", format=",")])
                st.altair_chart(chart, use_container_width=True)
            names = {"total_followers": "Followers", "profile_viewers": "Profile viewers (7d)",
                     "search_appearances": "Search appearances", "post_impressions": "Post impressions (7d)"}
            table = hist[["date"] + [c for c in linkedin_stats.FIELDS if c in hist]].iloc[::-1].rename(columns=names)
            st.dataframe(table, hide_index=True, use_container_width=True,
                         column_config={"date": st.column_config.DateColumn("Date", format="MMM D, YYYY")})
        if sheets_store.configured():
            st.caption("Saved permanently in your Google Sheet (LinkedIn tab).")
        else:
            st.caption("Saved on this app's disk, which resets when Streamlit restarts. Set up Google Sheets on the "
                       "Connections page to keep your history.")


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

    k = st.columns(4)
    k[0].metric("Posts (30 days)", len(last30), delta(len(last30), len(prev30)))
    k[1].metric("Interactions (30 days)", f"{int(last30['interactions'].sum()):,}",
                delta(last30["interactions"].sum(), prev30["interactions"].sum()))
    imp = last30["impressions"].sum()
    k[2].metric("Impressions / views (30 days)", f"{int(imp):,}" if imp else "–")
    er = last30[TARGET].mean()
    k[3].metric("Avg engagement rate", f"{er:.2%}" if pd.notna(er) else "–",
                help="(likes + comments + shares + clicks + saves) / impressions")

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
    table = table.assign(platform=table["platform"].map(pname),
                         text=table["text"].str.slice(0, 140))
    st.dataframe(table[["posted_at", "platform", "media_type", "text", "impressions", "likes", "comments",
                        "shares", "interactions", TARGET]],
                 hide_index=True, use_container_width=True,
                 column_config={"posted_at": st.column_config.DatetimeColumn("Posted", format="MMM D, YYYY"),
                                TARGET: st.column_config.NumberColumn("Engagement rate", format="percent"),
                                "text": st.column_config.TextColumn("Post", width="large")})


st.title("Dashboard")
show_flash()
creds = cx.meta_credentials()
source = "buffer" if buffer_api.configured() else ("meta" if creds else None)

if source:
    if source == "buffer":
        data = load_buffer(os.environ["BUFFER_API_KEY"][-6:])
        note = "Live from Buffer · Buffer updates post metrics about once a day"
        loader = load_buffer
        if creds:  # followers come from the direct Facebook & Instagram connection
            meta = load_meta_accounts(cx.version())
            data = {**data, "accounts": merge_accounts(data["accounts"], meta["accounts"]),
                    "errors": data["errors"] + meta["errors"]}
    else:
        data = load_live(cx.version())
        note = "Live from Facebook & Instagram · refreshed at most every 10 minutes"
        loader = load_live
    c1, c2, c3 = st.columns([2, 1, 1])
    c1.caption(f"{note} · {datetime.now():%I:%M %p}")
    if c2.button("Refresh now", use_container_width=True):
        loader.clear()
        load_meta_accounts.clear()
        st.rerun()
    if c3.button("Save to ML dataset", use_container_width=True, disabled=data["posts"].empty,
                 help="Adds these posts to data/processed/posts.csv so the model learns from your real results."):
        existing = pd.read_csv(POSTS_CSV) if POSTS_CSV.exists() else data["posts"].iloc[0:0]
        combine(existing, data["posts"]).to_csv(POSTS_CSV, index=False)
        flash(f"Saved {len(data['posts'])} posts to the dataset. Retrain the model in the notebook to use them.")
        st.rerun()
    for err in data["errors"]:
        st.warning(err)
    render_accounts(merge_accounts(data["accounts"], []))
    linkedin_editor()
    if data["posts"].empty:
        st.info("Connected, but no posts came back yet.")
    else:
        render_posts(data["posts"], data["accounts"], live=True)
else:
    st.warning("Showing **sample (fake) data**. Connect Buffer (or Facebook & Instagram) to see your live numbers.")
    st.page_link("views/connections.py", label="Go to Connections")
    render_accounts(merge_accounts([], []))
    linkedin_editor()
    if POSTS_CSV.exists():
        render_posts(load_sample(POSTS_CSV.stat().st_mtime), [], live=False)

profile = cx.linkedin_profile()
if profile:
    st.caption(f"LinkedIn connected as {profile.get('name')}. LinkedIn stats need API approval, so they "
               "aren't shown here yet.")
