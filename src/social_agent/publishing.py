"""Publish approved drafts. Shared by the connectors (agent) and the Streamlit review page (you).

Every path goes through review_queue.require_approved, so an unapproved draft can never be posted.
Main path: Buffer (all platforms, scheduling). Fallback: Facebook/Instagram directly through Meta.
"""
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import buffer_api, image_host
from . import review_queue as rq
from .loaders.meta_api import MetaAPIError, MetaClient

SUPPORTED_PLATFORMS = ("facebook", "instagram")


class PublishError(Exception):
    pass


def publish_post(draft_id: int, client: MetaClient | None = None) -> str:
    """Publish or schedule an approved post draft. Returns a short status message."""
    try:
        draft = rq.require_approved(draft_id, kind="post")
    except PermissionError as e:
        raise PublishError(str(e)) from e
    if draft["platform"] not in SUPPORTED_PLATFORMS:
        raise PublishError(f"Posting to {draft['platform']} isn't connected yet (only Facebook and Instagram).")
    if draft["platform"] == "instagram" and not (draft["image_url"] or "").startswith("http"):
        raise PublishError("Instagram needs a public image URL. Export the design with the Canva connector "
                           "(export_design) and put that URL on the draft.")
    try:
        client = client or MetaClient()
        if draft["platform"] == "facebook":
            when = None
            if draft["suggested_time"]:
                t = datetime.fromisoformat(draft["suggested_time"])
                if (t - datetime.now()).total_seconds() > 15 * 60:  # Meta needs at least ~10 min lead time
                    when = int(t.timestamp())
            post_id = client.publish_facebook_post(draft["text"], scheduled_unix=when)
            status = "scheduled" if when else "published"
        else:
            post_id = client.publish_instagram_image(draft["image_url"], draft["text"])
            status = "published"
    except (MetaAPIError, ValueError) as e:
        rq.mark_done(draft_id, "failed")
        raise PublishError(str(e)) from e
    rq.mark_done(draft_id, status, external_id=post_id)
    return f"Draft #{draft_id} {status} on {draft['platform']} (post id {post_id})."


def send_reply(draft_id: int, client: MetaClient | None = None) -> str:
    """Post an approved comment reply. Returns a short status message."""
    try:
        draft = rq.require_approved(draft_id, kind="reply")
    except PermissionError as e:
        raise PublishError(str(e)) from e
    try:
        client = client or MetaClient()
        reply_id = client.reply_to_comment(draft["reply_to_comment_id"], draft["text"], draft["platform"])
    except (MetaAPIError, ValueError) as e:
        rq.mark_done(draft_id, "failed")
        raise PublishError(str(e)) from e
    rq.mark_done(draft_id, "published", external_id=reply_id)
    return f"Reply draft #{draft_id} posted (reply id {reply_id})."


# ---------- Buffer (main path) ----------

ROOT = Path(__file__).resolve().parents[2]


def local_tz():
    """Your timezone for suggested times. Set APP_TIMEZONE (e.g. Asia/Manila); Streamlit Cloud runs on UTC."""
    name = os.getenv("APP_TIMEZONE")
    return ZoneInfo(name) if name else datetime.now().astimezone().tzinfo


def schedule_with_buffer(draft_id: int, use_queue: bool = False) -> str:
    """Upload the approved graphic to Cloudinary (if it's a local file) and schedule the post in Buffer:
    at the draft's suggested time, or in the next Buffer queue slot when there's no future time / use_queue."""
    try:
        draft = rq.require_approved(draft_id, kind="post")
    except PermissionError as e:
        raise PublishError(str(e)) from e
    image_url = draft.get("image_url")
    try:
        if image_url and not image_url.startswith("http"):
            local = ROOT / image_url
            if not local.is_file():
                raise PublishError(f"Graphic not found: {image_url}")
            image_url = image_host.upload(local)
        client = buffer_api.BufferClient()
        channel = client.channel_for(draft["platform"], buffer_api.preferred_channels().get(draft["platform"]))
        due = None
        if draft.get("suggested_time") and not use_queue:
            t = datetime.fromisoformat(draft["suggested_time"])
            t = t if t.tzinfo else t.replace(tzinfo=local_tz())
            if t > datetime.now(t.tzinfo) + timedelta(minutes=5):
                due = t
        post = client.create_post(channel["id"], draft["text"], image_url=image_url, due_at=due)
    except (buffer_api.BufferError, image_host.ImageHostError) as e:
        rq.set_publish_result(draft_id, "failed", image_url=image_url if image_url else None)
        raise PublishError(str(e)) from e
    rq.set_publish_result(draft_id, "scheduled", external_id=post["id"], channel_id=channel["id"], image_url=image_url)
    when = f"for {due:%a %d %b, %I:%M %p}" if due else "in your Buffer queue"
    return f"Draft #{draft_id} scheduled on {channel.get('displayName') or channel.get('name')} {when}."
