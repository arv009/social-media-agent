"""Review queue: approve the caption, then the graphic; approved posts are scheduled in Buffer.

Flow for posts with a graphic:
  Captions tab (approve caption) -> graphic is created -> Graphics tab (approve graphic)
  -> image uploaded to Cloudinary -> post scheduled in Buffer (suggested time or Buffer queue)
"""
import sys
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st
from ui import PLATFORMS, ROOT, flash, pname, show_flash

from social_agent import buffer_api, graphics, image_host, publishing
from social_agent import connections as cx
from social_agent import review_queue as rq

CHAR_LIMIT = {"linkedin": 3000, "facebook": 63206, "instagram": 2200}
META_READY = cx.meta_credentials() is not None
BUFFER_READY = buffer_api.configured()
CLOUDINARY_READY = image_host.configured()


def parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def time_inputs(d: dict, key: str) -> str:
    """Date + time pickers; returns ISO string (your local time)."""
    current = parse_time(d["suggested_time"]) or datetime.combine(date.today() + timedelta(days=1), time(9, 0))
    c1, c2 = st.columns(2)
    day = c1.date_input("Post date", current.date(), key=f"date_{key}")
    hour = c2.time_input("Time", current.time(), key=f"time_{key}", step=900)
    return datetime.combine(day, hour).isoformat(timespec="minutes")


def text_stats(text: str, platform: str):
    limit = CHAR_LIMIT.get(platform, 3000)
    hashtags = sum(w.startswith("#") for w in text.split())
    st.caption(f"{'Over the limit: ' if len(text) > limit else ''}{len(text):,} / {limit:,} characters · "
               f"{len(text.split())} words · {hashtags} hashtags")


def draft_header(d: dict):
    kind = "Reply" if d["kind"] == "reply" else "Post"
    st.markdown(f"#### {kind} for {pname(d['platform'])} · #{d['id']}")
    st.caption(f"Created {d['created_at'].replace('T', ' ')}")


def show_image(d: dict):
    img = d.get("image_url")
    if not img:
        return
    if img.startswith("http"):
        st.image(img, use_container_width=True)
    elif (ROOT / img).is_file():
        st.image(str(ROOT / img), use_container_width=True)
    else:
        st.caption(f"Image not found: {img}")


def notes_panel(d: dict):
    if d["predicted_engagement"] is not None:
        st.metric("Predicted engagement rate", f"{d['predicted_engagement']:.2%}")
    if d["agent_notes"]:
        st.info(f"**Agent's reasoning:** {d['agent_notes']}")
    if d["reviewer_note"]:
        st.warning(f"**Earlier review note:** {d['reviewer_note']}")


def make_graphic(d: dict, spec: dict | None = None) -> str:
    """Create the post's graphic from its plan (layout, headline...). Returns the image path."""
    spec = spec or rq.graphic_spec(d) or {"layout": "question", "headline": d["text"].split("\n")[0][:80]}
    path = graphics.make_post_graphic(platform=d["platform"], **{k: v for k, v in spec.items() if v})
    return str(path.relative_to(ROOT))


def finish(d_id: int, use_queue: bool = False):
    """After the last approval: schedule in Buffer when it's set up."""
    if not BUFFER_READY:
        flash(f"Draft #{d_id} approved. Add BUFFER_API_KEY to schedule it automatically (see Connections).")
        return
    try:
        flash(publishing.schedule_with_buffer(d_id, use_queue=use_queue))
    except publishing.PublishError as e:
        flash(f"Draft #{d_id} approved, but scheduling failed: {e}", "error")


def when_choice(d: dict, key: str) -> tuple[str, bool]:
    """Post time controls. Returns (suggested_time ISO, use Buffer queue?)."""
    mode = st.radio("When to post", ["Suggested time", "Next Buffer queue slot"], key=f"mode_{key}",
                    horizontal=True, help="Suggested time comes from the model trained on your results. "
                                          "The queue uses the posting schedule you set in Buffer.")
    when = time_inputs(d, key) if mode == "Suggested time" else d["suggested_time"]
    return when, mode != "Suggested time"


# ---------- step 1: caption ----------

def caption_card(d: dict):
    with st.container(border=True):
        left, right = st.columns([3, 2], gap="large")
        with left:
            draft_header(d)
            if d["kind"] == "reply":
                st.markdown(f"**Comment:** “{d['comment_text']}”")
            text = st.text_area("Caption", d["text"], height=220, key=f"text_{d['id']}")
            text_stats(text, d["platform"])
            note = st.text_input("Note for the agent (needed to reject)", key=f"note_{d['id']}",
                                 placeholder="e.g. Make it shorter and add a question at the end")
            graphic = rq.needs_graphic(d)
            b1, b2, b3 = st.columns(3)
            label = "Approve caption" if graphic else "Approve"
            if b1.button(label, key=f"approve_{d['id']}", type="primary", use_container_width=True):
                rq.human_edit(d["id"], text=text)
                if graphic:
                    with st.spinner("Creating the graphic…"):
                        image = d["image_url"] or make_graphic(d)
                    rq.set_graphic(d["id"], image)
                    st.session_state.goto_section = "graphics"
                    flash(f"Caption #{d['id']} approved. Here's its graphic: approve it to schedule the post.")
                else:
                    rq.review(d["id"], approve=True, note=note or None)
                    if d["kind"] == "post":
                        finish(d["id"])
                    else:
                        flash(f"Reply #{d['id']} approved. Send it from the Approved tab.")
                st.rerun()
            if b2.button("Save", key=f"save_{d['id']}", use_container_width=True):
                rq.human_edit(d["id"], text=text)
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
            spec = rq.graphic_spec(d)
            if spec:
                st.caption(f"Planned graphic: **{spec.get('layout', 'question')}** layout · “{spec.get('headline', '')}”")
            show_image(d)
            notes_panel(d)


# ---------- step 2: graphic ----------

def graphic_card(d: dict):
    spec = rq.graphic_spec(d) or {"layout": "question", "headline": ""}
    with st.container(border=True):
        left, right = st.columns([2, 3], gap="large")
        with left:
            show_image(d)
            if d["design_link"]:
                st.link_button("Open in Canva", d["design_link"])
        with right:
            draft_header(d)
            with st.expander("Caption (approved)"):
                st.markdown(d["text"].replace("\n", "  \n"))
            with st.expander("Change the graphic"):
                layout = st.selectbox("Layout", graphics.LAYOUTS, key=f"layout_{d['id']}",
                                      index=graphics.LAYOUTS.index(spec.get("layout", "question")))
                headline = st.text_input("Headline", spec.get("headline", ""), key=f"hl_{d['id']}")
                label = st.text_input("Label / subject", spec.get("label", ""), key=f"lb_{d['id']}")
                items = st.text_area("List items (one per line, list layout)", "\n".join(spec.get("items") or []),
                                     key=f"it_{d['id']}")
                subtext = st.text_area("Body text (card layout)", spec.get("subtext", ""), key=f"st_{d['id']}")
                if st.button("Regenerate graphic", key=f"regen_{d['id']}"):
                    new = {"layout": layout, "headline": headline, "label": label, "subtext": subtext,
                           "items": [i.strip() for i in items.splitlines() if i.strip()] or None}
                    if layout == "list" and not new["items"]:
                        st.error("The list layout needs at least one item.")
                    else:
                        rq.set_graphic(d["id"], make_graphic(d, new), new)
                        st.rerun()
            when, use_queue = when_choice(d, str(d["id"]))
            if BUFFER_READY and not CLOUDINARY_READY and (d.get("image_url") or "").startswith("data/"):
                st.warning("Add CLOUDINARY_URL so the image can be sent to Buffer (see Connections).")
            b1, b2 = st.columns(2)
            go = "Approve & schedule" if BUFFER_READY else "Approve graphic"
            if b1.button(go, key=f"gapprove_{d['id']}", type="primary", use_container_width=True):
                rq.human_edit(d["id"], suggested_time=when)
                rq.set_status(d["id"], "approved")
                with st.spinner("Uploading and scheduling…"):
                    finish(d["id"], use_queue=use_queue)
                st.session_state.goto_section = "scheduled" if BUFFER_READY else "approved"
                st.rerun()
            if b2.button("Back to caption", key=f"gback_{d['id']}", use_container_width=True):
                rq.send_back_to_pending(d["id"])
                st.rerun()
            notes_panel(d)


# ---------- approved, not yet scheduled ----------

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
                st.caption(f"Suggested time: {when:%a %d %b %Y, %I:%M %p}")
            cols = st.columns(3)
            if d["kind"] == "post":
                if cols[0].button("Schedule in Buffer", key=f"buf_{d['id']}", type="primary",
                                  disabled=not BUFFER_READY, use_container_width=True):
                    finish(d["id"])
                    st.rerun()
                if cols[1].button("Add to Buffer queue", key=f"bufq_{d['id']}", disabled=not BUFFER_READY,
                                  use_container_width=True):
                    finish(d["id"], use_queue=True)
                    st.rerun()
            elif cols[0].button("Send reply", key=f"rep_{d['id']}", type="primary", disabled=not META_READY,
                                use_container_width=True):
                try:
                    flash(publishing.send_reply(d["id"]))
                except publishing.PublishError as e:
                    flash(f"Couldn't send #{d['id']}: {e}", "error")
                st.rerun()
            if cols[2].button("Back to review", key=f"back_{d['id']}", use_container_width=True):
                rq.send_back_to_pending(d["id"])
                st.rerun()
            if d["kind"] == "post" and not BUFFER_READY:
                st.caption("Add BUFFER_API_KEY (Connections page) to schedule from here.")
            if d["kind"] == "reply" and not META_READY:
                st.caption("Replies are sent through the Facebook & Instagram connection (Connections page).")
        with right:
            show_image(d)
            notes_panel(d)


# ---------- page ----------

st.title("Review queue")
show_flash()
counts = rq.counts()
k = st.columns(5)
k[0].metric("Captions to review", counts["pending"])
k[1].metric("Graphics to review", counts["design_review"])
k[2].metric("Approved, not scheduled", counts["approved"])
k[3].metric("Scheduled / published", counts["scheduled"] + counts["published"])
k[4].metric("Failed", counts["failed"])
if not BUFFER_READY:
    st.caption("Buffer isn't connected yet: approved posts wait in the Approved tab. Set it up on Connections.")
platform_filter = st.pills("Platforms", PLATFORMS, selection_mode="multi", default=PLATFORMS,
                           format_func=pname) or PLATFORMS


def filtered(*statuses: str) -> list[dict]:
    rows = [d for s in statuses for d in rq.list_drafts(status=s, limit=200)]
    return [d for d in sorted(rows, key=lambda r: r["id"]) if d["platform"] in platform_filter]


# A remembered selector instead of st.tabs: tabs jump back to the first one after every click.
SECTIONS = {"captions": f"1 · Captions ({counts['pending']})", "graphics": f"2 · Graphics ({counts['design_review']})",
            "approved": f"Approved ({counts['approved']})",
            "scheduled": f"Scheduled ({counts['scheduled'] + counts['published']})", "history": "History"}
if st.session_state.get("review_section") is None:
    st.session_state.review_section = "captions"
if "goto_section" in st.session_state:
    st.session_state.review_section = st.session_state.pop("goto_section")
section = st.segmented_control("Section", list(SECTIONS), format_func=SECTIONS.get, key="review_section",
                               label_visibility="collapsed") or "captions"

if section == "captions":
    drafts = filtered("pending")
    if not drafts:
        st.success("No captions to review. Ask the AI agent in the left panel to write a post.")
        if st.button("Load demo drafts", help="Adds 4 example drafts so you can try the review flow."):
            sys.path.insert(0, str(ROOT / "scripts"))
            from seed_demo_drafts import seed_demo
            flash(f"Added {seed_demo()} demo drafts.")
            st.rerun()
    for d in drafts:
        caption_card(d)

elif section == "graphics":
    drafts = filtered("design_review")
    if not drafts:
        st.info("No graphics to review. They appear here after you approve a caption.")
    for d in drafts:
        graphic_card(d)

elif section == "approved":
    drafts = filtered("approved")
    if not drafts:
        st.info("Nothing waiting. Approved posts are scheduled in Buffer automatically when it's connected.")
    for d in drafts:
        approved_card(d)

elif section == "scheduled":
    drafts = filtered("scheduled", "published")
    if not drafts:
        st.info("No scheduled posts yet.")
    for d in reversed(drafts):
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            when = parse_time(d["suggested_time"])
            c1.markdown(f"**{pname(d['platform'])} #{d['id']}** · {d['status']}"
                        + (f" · {when:%a %d %b, %I:%M %p}" if when else ""))
            c1.caption(d["text"][:160] + ("…" if len(d["text"]) > 160 else ""))
            if d.get("image_url", "") and d["image_url"].startswith("http"):
                c2.image(d["image_url"], width=90)
    if drafts and BUFFER_READY:
        st.link_button("Open Buffer", "https://publish.buffer.com")

else:
    rows = [d for d in rq.list_drafts(limit=500) if d["platform"] in platform_filter]
    if rows:
        hist = pd.DataFrame(rows)[["id", "status", "kind", "platform", "text", "predicted_engagement",
                                   "suggested_time", "reviewer_note", "external_id", "updated_at"]]
        status_filter = st.multiselect("Status", rq.STATUSES, default=rq.STATUSES)
        st.dataframe(hist[hist["status"].isin(status_filter)], hide_index=True, use_container_width=True,
                     column_config={"predicted_engagement": st.column_config.NumberColumn(format="percent"),
                                    "text": st.column_config.TextColumn(width="large")})
        stuck = [d for d in rows if d["status"] in ("rejected", "failed")]
        if stuck:
            pick = st.selectbox("Send a rejected or failed draft back to review", [None] + [d["id"] for d in stuck],
                                format_func=lambda i: "Choose…" if i is None else f"#{i}")
            if pick and st.button("Back to review"):
                rq.send_back_to_pending(pick)
                st.rerun()
    else:
        st.info("No drafts yet.")
