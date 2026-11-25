"""The AI agent chat in the left panel."""
import json
import os

import anthropic
import streamlit as st

from social_agent import connections
from social_agent.agent import MODEL, model_name

SUGGESTIONS = [
    "Write a LinkedIn post about 3 tips for small business branding",
    "What kind of posts worked best for us?",
    "Show me the drafts waiting for review",
]


def _step_label(name: str, data: dict) -> str:
    args = json.dumps(data, ensure_ascii=False)
    return f"`{name}` {args[:90]}{'…' if len(args) > 90 else ''}"


def _run(text: str):
    from agent_runtime import get_runtime  # imported lazily: starts the connectors on first use

    steps: list[str] = []

    def on_event(kind, data):  # called from the agent's background thread: only collect, no st.* calls
        if kind == "tool_call":
            steps.append("Tool: " + _step_label(data["name"], data["input"]))
        elif kind == "tool_result" and data["is_error"]:
            steps.append("Error: " + data["text"][:160])
        elif kind == "model_switch":
            steps.append(f"{model_name(data['from'])} declined; continued with {model_name(data['to'])}")

    chat = st.session_state.chat
    chat.append({"role": "user", "content": text})
    try:
        rt = get_runtime(connections.version())
        answer, used, messages = rt.ask(st.session_state.agent_messages, text, on_event)
        st.session_state.agent_messages = messages
        chat.append({"role": "assistant", "content": answer, "steps": steps,
                     "model": used if used != MODEL else None})
    except anthropic.AuthenticationError:
        chat.append({"role": "assistant", "content": "The Claude API key isn't valid. Check ANTHROPIC_API_KEY."})
    except anthropic.RateLimitError:
        chat.append({"role": "assistant", "content": "Rate limited by the Claude API. Try again in a minute."})
    except anthropic.APIConnectionError:
        chat.append({"role": "assistant", "content": "Couldn't reach the Claude API. Check the internet connection."})
    except anthropic.APIStatusError as e:
        chat.append({"role": "assistant", "content": f"Claude API error {e.status_code}: {e.message}"})
    except Exception as e:  # noqa: BLE001 - show the problem in the chat instead of crashing the page
        chat.append({"role": "assistant", "content": f"Something went wrong: {e}"})


def render():
    st.session_state.setdefault("chat", [])
    st.session_state.setdefault("agent_messages", [])
    with st.sidebar:
        st.markdown("### AI agent")
        if not os.getenv("ANTHROPIC_API_KEY"):
            st.info("Add **ANTHROPIC_API_KEY** to `.env` (or the app's Secrets on Streamlit Cloud) to chat "
                    "with the agent.")
            return
        st.caption(f"{model_name(MODEL)} · steps up to Sonnet/Opus if needed")
        box = st.container(height=440, border=True)
        with box:
            if not st.session_state.chat:
                st.caption("Ask me to write posts, design graphics, check results or draft comment replies. "
                           "Drafts go to the Review queue for your approval.")
                for s in SUGGESTIONS:
                    if st.button(s, key=f"sugg_{s}", use_container_width=True):
                        st.session_state.pending_prompt = s
                        st.rerun()
            for msg in st.session_state.chat:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
                    if msg.get("steps"):
                        with st.expander(f"{len(msg['steps'])} steps"):
                            for s in msg["steps"]:
                                st.markdown(s)
                    if msg.get("model"):
                        st.caption(f"Answered by {model_name(msg['model'])}")
        prompt = st.chat_input("Ask the agent…", key="agent_input")
        prompt = prompt or st.session_state.pop("pending_prompt", None)
        if prompt:
            with box, st.spinner("Working on it… (first message starts the connectors)"):
                _run(prompt)
            st.rerun()
        if st.session_state.chat and st.button("Clear chat", use_container_width=True):
            st.session_state.chat, st.session_state.agent_messages = [], []
            st.rerun()
