"""Review queue: approve, edit or reject what the agent drafted, then publish."""
import sys
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st
from ui import PLATFORM_ICON, ROOT, flash, pname, show_flash

from social_agent import connections as cx
from social_agent import publishing
from social_agent import review_queue as rq

CHAR_LIMIT = {"linkedin": 3000, "facebook": 63206, "instagram": 2200}
META_READY = cx.meta_credentials() is not None


def parse_time(value: str | None) -> datetime:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def time_inputs(d: dict, key: str) -> str:
    """Date + time pickers; returns ISO string."""
    current = parse_time(d["suggested_time"]) or datetime.combine(date.today() + timedelta(days=1), time(9, 0))
    c1, c2 = st.columns(2)
    day = c1.date_input("Post date", current.date(), key=f"date_{key}")
    hour = c2.time_input("Time", current.time(), key=f"time_{key}", step=900)
    return datetime.combine(day, hour).isoformat(timespec="minutes")


def text_stats(text: str, platform: str):
    limit = CHAR_LIMIT.get(platform, 3000)
    hashtags = sum(w.startswith("#") for w in text.split())
    over = len(text) > limit
    st.caption(f"{'⚠️ ' if over else ''}{len(text):,} / {limit:,} characters · {len(text.split())} words · "
               f"{hashtags} hashtags")


def draft_header(d: dict):
    icon = PLATFORM_ICON.get(d["platform"], "📝")
    kind = "Reply" if d["kind"] == "reply" else "Post"
    st.markdown(f"#### {icon} {kind} for {pname(d['platform'])} · #{d['id']}")
    st.caption(f"Created {d['created_at'].replace('T', ' ')}")


def draft_side_panel(d: dict):
    img = d["image_url"]
    if img:
        if img.startswith("http"):
            st.image(img, use_container_width=True)
        elif (ROOT / img).is_file():
            st.image(str(ROOT / img), use_container_width=True)
            if d["platform"] == "instagram":
                st.caption("Local image: export it from Canva to get a public URL before publishing to Instagram.")
        else:
            st.caption(f"Image not found: {img}")
    if d["design_link"]:
        st.link_button("Open design", d["design_link"])
    if d["predicted_engagement"] is not None:
        st.metric("Predicted engagement rate", f"{d['predicted_engagement']:.2%}")
    if d["agent_notes"]:
        st.info(f"**Agent's reasoning:** {d['agent_notes']}")
    if d["reviewer_note"]:
        st.warning(f"**Earlier review note:** {d['reviewer_note']}")


# ---------- pending ----------

def pending_card(d: dict):
    with st.container(border=True):
        left, right = st.columns([3, 2], gap="large")
        with left:
            draft_header(d)
            if d["kind"] == "reply":
                st.markdown(f"**Comment:** “{d['comment_text']}”")
            text = st.text_area("Text", d["text"], height=220, key=f"text_{d['id']}")
            text_stats(text, d["platform"])
            when = time_inputs(d, str(d["id"])) if d["kind"] == "post" else None
            note = st.text_input("Note for the agent (needed to reject)", key=f"note_{d['id']}",
                                 placeholder="e.g. Make it shorter and add a question at the end")
            b1, b2, b3 = st.columns(3)
            if b1.button("Approve", key=f"approve_{d['id']}", type="primary", use_container_width=True):
                rq.human_edit(d["id"], text=text, suggested_time=when)
                rq.review(d["id"], approve=True, note=note or None)
                flash(f"Draft #{d['id']} approved.")
                st.rerun()
            if b2.button("Save", key=f"save_{d['id']}", use_container_width=True):
                rq.human_edit(d["id"], text=text, suggested_time=when)
                flash(f"Draft #{d['id']} saved.")
                st.rerun()
            if b3.button("Reject", key=f"reject_{d['id']}", use_container_width=True):
                if not note.strip():
                    st.error("Add a note so the agent knows what to change.")
                else:
                    rq.review(d["id"], approve=False, note=note.strip())
                    flash(f"Draft #{d['id']} rejected. Ask the agent to revise it.", "info")
                    st.rerun()
        with right:
            draft_side_panel(d)


# ---------- approved ----------

def approved_card(d: dict):
    with st.container(border=True):
        left, right = st.columns([3, 2], gap="large")
        with left:
            draft_header(d)
            if d["kind"] == "reply":
                st.markdown(f"**Comment:** “{d['comment_text']}”")
            st.markdown(d["text"].replace("\n", "  \n"))
            when = parse_time(d["suggested_time"])
            if d["kind"] == "post" and when:
                st.caption(f"🕘 Suggested time: {when:%a %d %b %Y, %I:%M %p}")

            supported = d["platform"] in publishing.SUPPORTED_PLATFORMS
            future = d["kind"] == "post" and when and when > datetime.now() + timedelta(minutes=15)
            if d["kind"] == "reply":
                label = "💬 Send reply"
            elif d["platform"] == "facebook" and future:
                label = "🗓 Schedule"
            else:
                label = "🚀 Publish now"

            b1, b2 = st.columns(2)
            can_publish = META_READY and supported
            if b1.button(label, key=f"pub_{d['id']}", type="primary", disabled=not can_publish,
                         use_container_width=True):
                try:
                    fn = publishing.send_reply if d["kind"] == "reply" else publishing.publish_post
                    flash(fn(d["id"]))
                except publishing.PublishError as e:
                    flash(f"Couldn't publish #{d['id']}: {e}", "error")
                st.rerun()
            if b2.button("↩️ Back to review", key=f"back_{d['id']}", use_container_width=True):
                rq.send_back_to_pending(d["id"])
                st.rerun()
            if not supported:
                st.caption(f"Posting to {pname(d['platform'])} isn't connected yet. Post it manually, "
                           "or wait for the LinkedIn/Buffer connector.")
            elif not META_READY:
                st.caption("Connect Facebook & Instagram on the Connections page to publish from here.")
        with right:
            draft_side_panel(d)


# ---------- page ----------

st.title("📝 Review queue")
show_flash()
counts = rq.counts()
k = st.columns(4)
k[0].metric("Waiting for review", counts["pending"])
k[1].metric("Approved, not posted", counts["approved"])
k[2].metric("Scheduled / published", counts["scheduled"] + counts["published"])
k[3].metric("Failed", counts["failed"])
platform_filter = st.pills("Platforms", list(PLATFORM_ICON), selection_mode="multi", default=list(PLATFORM_ICON),
                           format_func=lambda p: f"{PLATFORM_ICON[p]} {pname(p)}") or list(PLATFORM_ICON)


def filtered(status: str) -> list[dict]:
    rows = rq.list_drafts(status=status, limit=200)
    return [d for d in reversed(rows) if d["platform"] in platform_filter]


tab_pending, tab_approved, tab_history = st.tabs([
    f"To review ({counts['pending']})", f"Approved ({counts['approved']})", "History"])

with tab_pending:
    drafts = filtered("pending")
    if not drafts:
        st.success("Nothing to review. Ask the AI agent in the left panel to write a post.")
        if st.button("Load demo drafts", help="Adds 4 example drafts so you can try the review flow."):
            sys.path.insert(0, str(ROOT / "scripts"))
            from seed_demo_drafts import seed_demo
            flash(f"Added {seed_demo()} demo drafts.")
            st.rerun()
    for d in drafts:
        pending_card(d)

with tab_approved:
    drafts = filtered("approved")
    if not drafts:
        st.info("No approved drafts waiting to be posted.")
    for d in drafts:
        approved_card(d)

with tab_history:
    rows = [d for d in rq.list_drafts(limit=500) if d["platform"] in platform_filter]
    if rows:
        hist = pd.DataFrame(rows)[["id", "status", "kind", "platform", "text", "predicted_engagement",
                                   "suggested_time", "reviewer_note", "external_id", "updated_at"]]
        status_filter = st.multiselect("Status", rq.STATUSES, default=rq.STATUSES)
        st.dataframe(hist[hist["status"].isin(status_filter)], hide_index=True, use_container_width=True,
                     column_config={"predicted_engagement": st.column_config.NumberColumn(format="percent"),
                                    "text": st.column_config.TextColumn(width="large")})
        failed = [d for d in rows if d["status"] in ("rejected", "failed")]
        if failed:
            pick = st.selectbox("Send a rejected or failed draft back to review",
                                [None] + [d["id"] for d in failed],
                                format_func=lambda i: "Choose…" if i is None else f"#{i}")
            if pick and st.button("↩️ Back to review"):
                rq.send_back_to_pending(pick)
                st.rerun()
    else:
        st.info("No drafts yet.")
