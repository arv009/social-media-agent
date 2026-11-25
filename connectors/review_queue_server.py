"""Review Queue connector: the agent saves drafts here for you to approve.

There is intentionally NO approve tool. Approving is done by a human with
scripts/review.py (or the Streamlit page in a later stage).
"""
import json

from _common import to_json
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from social_agent import review_queue as rq

mcp = MCPServer("review-queue")


@mcp.tool()
def submit_post_draft(platform: str, text: str, media_type: str = "none", image_url: str | None = None,
                      design_link: str | None = None, suggested_time: str | None = None,
                      predicted_engagement: float | None = None, agent_notes: str | None = None,
                      graphic_layout: str | None = None, graphic_headline: str | None = None,
                      graphic_label: str | None = None, graphic_items_json: str | None = None,
                      graphic_subtext: str | None = None) -> str:
    """Save a social media post draft to the review queue for a human to approve.

    Args:
        platform: linkedin, facebook or instagram.
        text: The full post text, including hashtags.
        media_type: none, image, video or carousel.
        image_url: Public URL of the design image (required later to publish on Instagram).
        design_link: Link to the editable design (e.g. Canva) for the reviewer.
        suggested_time: When to post, ISO format local time, e.g. 2026-12-01T09:00.
        predicted_engagement: Engagement rate predicted by the analytics model (e.g. 0.052).
        agent_notes: Short reason for the choices made (shown to the reviewer).
        graphic_layout: Plan for the post's graphic, created AFTER the human approves the caption:
            cover, list, question or card. Leave empty for a text-only post.
        graphic_headline: Short headline for the graphic (under 8 words; under 6 for list).
        graphic_label: Gold tag above the list headline, or the email subject for the card layout.
        graphic_items_json: For the list layout: JSON list of 3-5 short items.
        graphic_subtext: Body text for the card layout (under 25 words).
    """
    spec = None
    if graphic_layout:
        items = None
        if graphic_items_json:
            try:
                items = [str(i) for i in json.loads(graphic_items_json)]
            except (ValueError, TypeError) as e:
                raise ToolError(f"graphic_items_json must be a JSON list of strings ({e}).") from e
        if graphic_layout not in ("cover", "list", "question", "card"):
            raise ToolError("graphic_layout must be cover, list, question or card.")
        if graphic_layout == "list" and not items:
            raise ToolError("The list layout needs 3-5 items in graphic_items_json.")
        spec = {"layout": graphic_layout, "headline": graphic_headline or "", "label": graphic_label or "",
                "items": items, "subtext": graphic_subtext or ""}
        media_type = "image" if media_type == "none" else media_type
    draft_id = rq.add_draft(platform, text, kind="post", media_type=media_type, image_url=image_url,
                            design_link=design_link, suggested_time=suggested_time,
                            predicted_engagement=predicted_engagement, agent_notes=agent_notes, graphic_spec=spec)
    return f"Saved as draft #{draft_id} (status: pending). A human needs to approve it before it can be published."


@mcp.tool()
def submit_reply_draft(platform: str, comment_id: str, comment_text: str, reply_text: str,
                       agent_notes: str | None = None) -> str:
    """Save a draft reply to a comment for a human to approve.

    Args:
        platform: facebook or instagram.
        comment_id: The platform's id of the comment being replied to.
        comment_text: The original comment (so the reviewer has context).
        reply_text: The proposed reply.
        agent_notes: Short reason for the reply (shown to the reviewer).
    """
    draft_id = rq.add_draft(platform, reply_text, kind="reply", reply_to_comment_id=comment_id,
                            comment_text=comment_text, agent_notes=agent_notes)
    return f"Saved as reply draft #{draft_id} (status: pending). A human needs to approve it."


@mcp.tool()
def list_drafts(status: str | None = None, kind: str | None = None, limit: int = 20) -> str:
    """List drafts in the review queue, newest first.

    Args:
        status: Filter by pending, approved, rejected, scheduled, published or failed.
        kind: Filter by post or reply.
        limit: Maximum number of drafts to return.
    """
    return to_json(rq.list_drafts(status=status, kind=kind, limit=limit))


@mcp.tool()
def get_draft(draft_id: int) -> str:
    """Get one draft, including the reviewer's note if it was rejected."""
    draft = rq.get_draft(draft_id)
    return to_json(draft) if draft else f"Draft {draft_id} not found."


@mcp.tool()
def revise_draft(draft_id: int, new_text: str) -> str:
    """Rewrite a pending or rejected draft (for example, after reading the reviewer's note).
    The draft goes back to pending for another review."""
    try:
        rq.update_draft_text(draft_id, new_text)
    except ValueError as e:
        raise ToolError(f"{e}")
    return f"Draft #{draft_id} updated and back in the queue as pending."


if __name__ == "__main__":
    mcp.run()
