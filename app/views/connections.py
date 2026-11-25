"""Connections: connect social accounts and apps (Facebook & Instagram, LinkedIn, Canva, Google Drive...)."""
import os

import streamlit as st
from ui import base_url, flash, show_flash

from social_agent import connections as cx
from social_agent.agent import MODEL, model_name

st.title("🔌 Connections")
st.caption("Connect your accounts so the dashboard shows live data and the agent can use them. "
           "Each Connect button opens the service's own sign-in page in a new tab.")
show_flash()

redirect = base_url()


def provider_card(key: str):
    p = cx.PROVIDERS[key]
    s = cx.status(key)
    with st.container(border=True):
        top, action = st.columns([4, 1.4], vertical_alignment="center")
        with top:
            badge = ":green-badge[Connected]" if s["connected"] else (
                ":orange-badge[Needs setup]" if s["missing"] else ":gray-badge[Not connected]")
            st.markdown(f"#### {p['icon']} {p['name']} {badge}")
            st.caption(p["what"])
            if s["connected"] and s["account"]:
                st.markdown(f"Signed in as **{s['account']}**")
        with action:
            if s["connected"]:
                if st.button("Disconnect", key=f"disc_{key}", use_container_width=True):
                    cx.disconnect(key)
                    flash(f"{p['name']} disconnected.", "info")
                    st.rerun()
            elif s["missing"]:
                st.button("Connect", key=f"conn_{key}", disabled=True, use_container_width=True,
                          help="Add the app credentials first (see Setup).")
            else:
                st.link_button("Connect", cx.auth_url(key, redirect), type="primary", use_container_width=True)
        if key == "meta" and s["connected"]:
            pages = cx.meta_pages()
            if len(pages) > 1:
                current = (cx.meta_credentials() or {}).get("page_id")
                labels = {pg["id"]: pg["name"] + (f" (@{pg['ig_username']})" if pg["ig_username"] else "")
                          for pg in pages}
                pick = st.selectbox("Facebook Page to use", list(labels), format_func=labels.get,
                                    index=list(labels).index(current) if current in labels else 0)
                if pick != current:
                    cx.select_meta_page(pick)
                    st.rerun()
            if not (cx.meta_credentials() or {}).get("ig_user_id"):
                st.caption("No Instagram account is linked to this Page. Link an Instagram Business/Creator "
                           "account to the Page in Meta Business Suite, then reconnect.")
        if key == "linkedin" and s["connected"]:
            st.caption("LinkedIn post analytics need LinkedIn's Community Management API approval, so the "
                       "dashboard can't show LinkedIn stats yet. Use CSV exports for LinkedIn results.")
        if not s["connected"]:
            with st.expander("Setup" + (" (required)" if s["missing"] else "")):
                st.markdown(f"1. {p['setup']}")
                st.markdown("2. Use this as the redirect URL:")
                st.code(redirect, language=None)
                st.markdown("3. Add these to `.env` (local) or the app's **Secrets** (Streamlit Cloud):")
                st.code("\n".join(f'{v} = "..."' for v in p["needs"]), language="toml")
                if s["missing"]:
                    st.caption("Missing: " + ", ".join(s["missing"]))


st.subheader("Social accounts")
provider_card("meta")
provider_card("linkedin")
with st.container(border=True):
    st.markdown("#### 🗓 Buffer :gray-badge[Coming later]")
    st.caption("Buffer's API access for new apps is limited. Facebook scheduling works through the Facebook "
               "connection meanwhile.")

st.subheader("Design & files")
provider_card("canva")
provider_card("google_drive")

st.subheader("AI")
with st.container(border=True):
    ok = bool(os.getenv("ANTHROPIC_API_KEY"))
    st.markdown(f"#### 🤖 Claude {':green-badge[Ready]' if ok else ':orange-badge[Needs setup]'}")
    st.caption(f"Powers the AI agent in the left panel. Model: {model_name(MODEL)}, stepping up to Sonnet 5.5 "
               "and Opus 5.5 when a request is declined.")
    if not ok:
        st.markdown("Get an API key at console.anthropic.com, then add it to `.env` or the app's Secrets:")
        st.code('ANTHROPIC_API_KEY = "sk-ant-..."', language="toml")

with st.expander("What the agent can use right now"):
    from agent_runtime import _runtimes  # only shows runtimes that are already running

    rt = next(iter(_runtimes.values()), None)
    if rt and rt.hub:
        st.code(rt.hub.status_table(), language=None)
    else:
        st.caption("The agent's connectors start with your first message in the AI agent panel.")

st.caption("Tokens are stored in the app's `secrets/` folder. On Streamlit Cloud that folder resets when the "
           "app restarts, so you may need to connect again after a restart.")
