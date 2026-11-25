"""Publish approved drafts. Shared by the Meta connector (agent) and the Streamlit review page (you).

Both paths go through review_queue.require_approved, so an unapproved draft can never be posted.
"""
from datetime import datetime

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
