"""Arvin Marketing Pro · Social Media Agent

    streamlit run app/streamlit_app.py

Pages: Dashboard (live social stats), Review queue, Insights, Connections.
Left panel: the AI agent.
"""
import hmac
import os

import streamlit as st
import ui  # noqa: F401 - sets up import paths and .env

from social_agent import connections as cx

st.set_page_config(page_title="Social Media Agent · Arvin Marketing Pro", page_icon=":material/campaign:", layout="wide")

# 1) Coming back from a Connect button: the service redirects here with ?code=...&state=...
#    Handled before the password check: it only works with the one-time state the app created.
params = st.query_params.to_dict()
if "state" in params and ("code" in params or "error" in params):
    try:
        _, message = cx.handle_callback(params)
        ui.flash(message + " You can close this tab and refresh the app's original tab, or keep working here.")
    except cx.ConnectError as e:
        ui.flash(str(e), "error")
    st.query_params.clear()

# 2) Optional password (strongly recommended on Streamlit Cloud: the app can post and spend API credits).
password = os.getenv("APP_PASSWORD")
if password and not st.session_state.get("authed"):
    st.title("Social Media Agent")
    entered = st.text_input("Password", type="password")
    if entered:
        if hmac.compare_digest(entered, password):
            st.session_state.authed = True
            st.rerun()
        st.error("Wrong password.")
    st.stop()

# 3) Pages and the agent panel.
pages = {
    "Workspace": [
        st.Page("views/dashboard.py", title="Dashboard", icon=":material/dashboard:", default=True),
        st.Page("views/review.py", title="Review queue", icon=":material/rate_review:"),
        st.Page("views/insights.py", title="Insights", icon=":material/insights:"),
    ],
    "Settings": [st.Page("views/connections.py", title="Connections", icon=":material/hub:")],
}
nav = st.navigation(pages)
with st.sidebar:
    st.markdown("**Arvin Marketing Pro**")

import agent_panel  # noqa: E402

agent_panel.render()
nav.run()
