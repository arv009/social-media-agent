"""Insights: what the ML model learned from past post results."""
import pandas as pd
import streamlit as st
from ui import PLATFORM_ICON, ROOT, pname

from social_agent import model as m
from social_agent.features import TARGET, build_features

POSTS_CSV = ROOT / "data/processed/posts.csv"


@st.cache_data(ttl=300)
def load_posts(mtime: float) -> pd.DataFrame:
    return build_features(pd.read_csv(POSTS_CSV))


st.title("💡 Insights")
st.caption("Patterns from past post results. The agent reads the same insights before writing.")
if not POSTS_CSV.exists():
    st.info("No performance data yet. Run `python scripts/build_dataset.py`.")
    st.stop()
df = load_posts(POSTS_CSV.stat().st_mtime)
if (df["source"] == "sample").all():
    st.warning("These numbers come from **sample (fake) data**. Save live data from the Dashboard or add your "
               "exports to see real insights.")
cols = st.columns(df["platform"].nunique())
for col, (platform, g) in zip(cols, df.groupby("platform")):
    col.metric(f"{PLATFORM_ICON.get(platform, '')} {pname(platform)}", f"{g[TARGET].mean():.2%}",
               help=f"Average engagement rate over {len(g)} posts")
left, right = st.columns(2)
with left:
    st.markdown("**Engagement rate by media type**")
    st.bar_chart(df.pivot_table(index="media_type", columns="platform", values=TARGET, aggfunc="mean")
                 .rename(columns=pname), stack=False)
with right:
    st.markdown("**Engagement rate by topic**")
    st.bar_chart(df.pivot_table(index="topic", columns="platform", values=TARGET, aggfunc="mean")
                 .rename(columns=pname), stack=False)
st.markdown("**What the agent is told before writing**")
st.code(m.insights_to_prompt(m.generate_insights(df)), language=None)
