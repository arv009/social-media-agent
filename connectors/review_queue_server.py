"""Review Queue connector: the agent saves drafts here for you to approve.

There is intentionally NO approve tool. Approving is done by a human with
scripts/review.py (or the Streamlit page in a later stage).
"""
from _common import to_json
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from social_agent import review_queue as rq

mcp = MCPServer("review-queue")


@mcp.tool()
def submit_post_draft(platform: str, text: str, media_type: str = "none", image_url: str | None = None,
                      design_link: str | None = None, suggested_time: str | None = None,
                      predicted_engagement: float | None = None, agent_notes: str | None = None) -> str:
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
    """
    draft_id = rq.add_draft(platform, text, kind="post", media_type=media_type, image_url=image_url,
                            design_link=design_link, suggested_time=suggested_time,
                            predicted_engagement=predicted_engagement, agent_notes=agent_notes)
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
