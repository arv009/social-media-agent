"""Connections: connect social accounts and apps (Facebook & Instagram, LinkedIn, Canva, Google Drive...)."""
import os

import streamlit as st
from ui import base_url, flash, show_flash

from social_agent import buffer_api, image_host, sheets_store
from social_agent import connections as cx
from social_agent.agent import MODEL, model_name

st.title("Connections")
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
            st.markdown(f"#### {p['name']} {badge}")
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


@st.cache_data(ttl=300, show_spinner=False)
def buffer_channels(_key_hint: str) -> list[dict]:
    return buffer_api.BufferClient().channels()


def buffer_card():
    ok = buffer_api.configured()
    with st.container(border=True):
        st.markdown(f"#### Buffer {':green-badge[Connected]' if ok else ':orange-badge[Needs setup]'} "
                    ":blue-badge[Recommended]")
        st.caption("Posting and scheduling to LinkedIn, Facebook and Instagram, plus post analytics for the "
                   "dashboard and the ML model, all through one key.")
        if not ok:
            st.markdown("1. In Buffer, connect your LinkedIn profile, Facebook Page and Instagram account.\n"
                        "2. Go to **publish.buffer.com → Settings → API** and create an API key.\n"
                        "3. Add it to `.env` or the app's **Secrets**, plus your timezone so suggested times are right:")
            st.code('BUFFER_API_KEY = "..."\nAPP_TIMEZONE = "Asia/Manila"', language="toml")
            return
        try:
            chans = buffer_channels(os.environ["BUFFER_API_KEY"][-6:])
        except buffer_api.BufferError as e:
            st.error(str(e))
            return
        if not chans:
            st.warning("No channels in Buffer yet. Connect your accounts inside Buffer first.")
            return
        prefs = buffer_api.preferred_channels()
        for platform in ("linkedin", "facebook", "instagram"):
            options = [c for c in chans if c["service"].lower() == platform]
            name = {"linkedin": "LinkedIn", "facebook": "Facebook", "instagram": "Instagram"}[platform]
            if not options:
                st.caption(f"{name}: not connected in Buffer")
                continue
            labels = {c["id"]: f"{c.get('displayName') or c.get('name')} ({c.get('descriptor') or c.get('type')})"
                      for c in options}
            ids = list(labels)
            current = prefs.get(platform) if prefs.get(platform) in labels else ids[0]
            pick = st.selectbox(f"{name} posts go to", ids, index=ids.index(current), format_func=labels.get,
                                key=f"bufch_{platform}", disabled=len(ids) == 1)
            if pick != prefs.get(platform):
                buffer_api.save_preferred_channel(platform, pick)
        tz = os.getenv("APP_TIMEZONE")
        st.caption(f"Timezone for suggested times: **{tz or 'not set (uses the server clock)'}**"
                   + ("" if tz else " · add APP_TIMEZONE, e.g. Asia/Manila"))


def cloudinary_card():
    ok = image_host.configured()
    with st.container(border=True):
        st.markdown(f"#### Cloudinary {':green-badge[Ready]' if ok else ':orange-badge[Needs setup]'}")
        st.caption("Hosts approved graphics at a permanent public link, which Buffer needs to attach images. Free plan.")
        if not ok:
            st.markdown("Sign up at **cloudinary.com** (free), copy the **API environment variable** from the "
                        "dashboard (it starts with `cloudinary://`), and add it to `.env` or Secrets:")
            st.code('CLOUDINARY_URL = "cloudinary://API_KEY:API_SECRET@CLOUD_NAME"', language="toml")


def sheets_card():
    ok = sheets_store.configured()
    with st.container(border=True):
        st.markdown(f"#### Google Sheets {':green-badge[Set up]' if ok else ':orange-badge[Needs setup]'}")
        st.caption("Permanent storage for your LinkedIn stats history (Streamlit Cloud's own disk resets on restart).")
        if ok:
            email = sheets_store.service_account_email()
            if email:
                st.caption(f"Service account: `{email}` (the sheet must be shared with it as Editor)")
            if st.button("Test connection", key="sheets_test"):
                try:
                    st.success(f"Connected to “{sheets_store.test_connection()}”.")
                except sheets_store.SheetsError as e:
                    st.error(str(e))
            return
        with st.expander("Setup (about 10 minutes)"):
            st.markdown(
                "1. Go to **console.cloud.google.com**, pick or create a project, then **APIs & Services → "
                "Library → Google Sheets API → Enable**.\n"
                "2. **IAM & Admin → Service Accounts → Create service account**: give it a name (e.g. "
                "*social-media-agent*), click **Done**.\n"
                "3. Open it → **Keys → Add key → Create new key → JSON**. A `.json` file downloads. Keep it private.\n"
                "4. Create a Google Sheet (e.g. *Social Media Agent data*). Click **Share** and add the service "
                "account's email (`...@...iam.gserviceaccount.com`, it's in the JSON as `client_email`) as **Editor**.\n"
                "5. Add to the app's **Secrets**: the sheet's link, and the whole JSON file between triple quotes:")
            st.code('DATA_SHEET_URL = "https://docs.google.com/spreadsheets/d/..."\n'
                    "GOOGLE_SERVICE_ACCOUNT_JSON = \'\'\'\n{ ...paste the whole .json file here... }\n\'\'\'",
                    language="toml")


st.subheader("Publishing & analytics")
buffer_card()
cloudinary_card()
sheets_card()

st.subheader("Direct connections (optional)")
st.caption("Buffer covers posting and analytics. Connect these only for extras: Facebook & Instagram for comment "
           "replies and same-day stats, LinkedIn for your profile.")
provider_card("meta")
provider_card("linkedin")

st.subheader("Design & files")
provider_card("canva")
provider_card("google_drive")

st.subheader("AI")
with st.container(border=True):
    ok = bool(os.getenv("ANTHROPIC_API_KEY"))
    st.markdown(f"#### Claude {':green-badge[Ready]' if ok else ':orange-badge[Needs setup]'}")
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
