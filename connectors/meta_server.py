"""Meta connector: Facebook Page + Instagram Business (read posts and comments, publish approved drafts).

Needs META_PAGE_ACCESS_TOKEN (+ META_PAGE_ID and/or META_IG_USER_ID) in .env.
Publishing tools only accept a review-queue draft id, and refuse unless a
human approved that draft. The agent can never post free text directly.
"""
from _common import ROOT, to_json
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from social_agent import publishing
from social_agent.loaders.meta_api import MetaAPIError, MetaClient
from social_agent.publishing import PublishError
from social_agent.schema import combine

mcp = MCPServer("meta")
_client: MetaClient | None = None


def client() -> MetaClient:
    global _client
    if _client is None:
        _client = MetaClient()
    return _client


@mcp.tool()
def list_recent_posts(platform: str, limit: int = 10) -> str:
    """Recent posts with their metrics (likes, comments, shares, impressions...).

    Args:
        platform: facebook or instagram.
        limit: How many posts to return.
    """
    try:
        c = client()
        df = c.fetch_instagram_posts(limit) if platform == "instagram" else c.fetch_facebook_posts(limit)
    except (MetaAPIError, ValueError) as e:
        raise ToolError(str(e)) from e
    if df.empty:
        return "No posts found."
    cols = ["post_id", "posted_at", "media_type", "impressions", "likes", "comments", "shares", "text"]
    return to_json(df[cols].to_dict("records"))


@mcp.tool()
def list_comments(post_id: str, platform: str, limit: int = 25) -> str:
    """Comments on one post, with author, time, and whether it already has a reply.

    Args:
        post_id: The post id (from list_recent_posts).
        platform: facebook or instagram.
        limit: Maximum number of comments.
    """
    try:
        return to_json(client().list_comments(post_id, platform, limit))
    except (MetaAPIError, ValueError) as e:
        raise ToolError(str(e)) from e


@mcp.tool()
def sync_metrics_to_dataset(max_posts: int = 100) -> str:
    """Download the latest post metrics from Facebook/Instagram and add them to data/processed/posts.csv,
    so the analytics model can learn from them (retrain afterwards with the notebook)."""
    import pandas as pd
    try:
        new = client().fetch_all(max_posts)
    except (MetaAPIError, ValueError) as e:
        raise ToolError(str(e)) from e
    if new.empty:
        return "No posts returned by Meta."
    path = ROOT / "data/processed/posts.csv"
    existing = pd.read_csv(path) if path.exists() else new.iloc[0:0]
    combined = combine(existing, new)
    combined.to_csv(path, index=False)
    skipped = sorted(client().skipped_metrics)
    return (f"Synced {len(new)} posts. Dataset now has {len(combined)} posts."
            + (f" Skipped retired metrics: {skipped}." if skipped else ""))


@mcp.tool()
def publish_approved_post(draft_id: int) -> str:
    """Publish (or schedule) a post draft that a human has APPROVED in the review queue.
    Facebook posts are scheduled at the draft's suggested_time if it's in the future.
    Instagram posts are published right away and need the draft's image_url.

    Args:
        draft_id: The review-queue draft id.
    """
    try:
        return publishing.publish_post(draft_id, client())
    except (PublishError, MetaAPIError, ValueError) as e:
        raise ToolError(str(e)) from e


@mcp.tool()
def send_approved_reply(draft_id: int) -> str:
    """Post a comment reply that a human has APPROVED in the review queue.

    Args:
        draft_id: The review-queue reply draft id.
    """
    try:
        return publishing.send_reply(draft_id, client())
    except (PublishError, MetaAPIError, ValueError) as e:
        raise ToolError(str(e)) from e


if __name__ == "__main__":
    mcp.run()
