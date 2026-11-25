"""Buffer connector: channels, recent posts with analytics, and syncing results into the ML dataset.

Needs BUFFER_API_KEY. Scheduling happens when a human approves the graphic in the Review queue
(the agent can't schedule unapproved posts).
"""
import pandas as pd
from _common import ROOT, to_json
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from social_agent.buffer_api import BufferClient, BufferError
from social_agent.schema import combine

mcp = MCPServer("buffer")
_client: BufferClient | None = None


def client() -> BufferClient:
    global _client
    if _client is None:
        try:
            _client = BufferClient()
        except BufferError as e:
            raise ToolError(str(e)) from e
    return _client


@mcp.tool()
def buffer_channels() -> str:
    """The social accounts connected in Buffer (LinkedIn, Facebook, Instagram...), with their ids and type."""
    try:
        chans = client().channels()
    except BufferError as e:
        raise ToolError(str(e)) from e
    return to_json([{k: c.get(k) for k in ("id", "service", "displayName", "descriptor", "isQueuePaused")}
                    for c in chans])


@mcp.tool()
def buffer_recent_posts(limit: int = 20, platform: str | None = None) -> str:
    """Recently published posts from Buffer with their results (impressions, likes/reactions, comments,
    shares, clicks, saves). Buffer refreshes metrics about once a day.

    Args:
        limit: How many posts (newest first).
        platform: Optional filter: linkedin, facebook or instagram.
    """
    try:
        df = client().sent_posts_frame(limit=limit if not platform else limit * 3)
    except BufferError as e:
        raise ToolError(str(e)) from e
    if df.empty:
        return "No published posts found in Buffer yet."
    if platform:
        df = df[df["platform"] == platform.lower()].head(limit)
    cols = ["posted_at", "platform", "media_type", "impressions", "likes", "comments", "shares", "clicks", "text"]
    return to_json(df[cols].assign(text=df["text"].str.slice(0, 200)).to_dict("records"))


@mcp.tool()
def sync_buffer_metrics_to_dataset(limit: int = 200) -> str:
    """Add the latest Buffer post results to data/processed/posts.csv so the ML model learns from them
    (retrain with the notebook afterwards)."""
    try:
        new = client().sent_posts_frame(limit=limit)
    except BufferError as e:
        raise ToolError(str(e)) from e
    if new.empty:
        return "No published posts in Buffer yet."
    path = ROOT / "data/processed/posts.csv"
    existing = pd.read_csv(path) if path.exists() else new.iloc[0:0]
    combined = combine(existing, new)
    combined.to_csv(path, index=False)
    return f"Synced {len(new)} posts from Buffer. The dataset now has {len(combined)} posts."


if __name__ == "__main__":
    mcp.run()
