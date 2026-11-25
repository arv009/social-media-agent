"""Buffer GraphQL API client (https://developers.buffer.com).

Auth: a personal API key from publish.buffer.com > Settings > API, in BUFFER_API_KEY.
One key covers every channel connected in your Buffer account (LinkedIn, Facebook, Instagram...).

Notes from Buffer's docs:
- GraphQL errors come back with HTTP 200; check the body. Rate limits are HTTP 429 with Retry-After.
- No file uploads: images are passed as a public, permanent HTTPS URL (we use Cloudinary).
- Post metrics are refreshed about once a day.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from .schema import to_standard

API = "https://api.buffer.com"
CHANNELS_FILE = Path(__file__).resolve().parents[2] / "secrets" / "buffer_channels.json"

# Buffer metric type -> our standard column (first match wins for each column)
METRIC_MAP = {
    "impressions": ["impressions", "views", "reach"],
    "reach": ["reach"],
    "likes": ["reactions", "likes"],
    "comments": ["comments"],
    "shares": ["shares", "reposts"],
    "clicks": ["clicks"],
    "saves": ["saves"],
}


class BufferError(Exception):
    pass


class BufferClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        self.key = api_key or os.getenv("BUFFER_API_KEY")
        if not self.key:
            raise BufferError("Buffer isn't connected. Add BUFFER_API_KEY (publish.buffer.com > Settings > API).")
        self.http = session or requests.Session()
        self._org_id: str | None = None

    def query(self, query: str, variables: dict | None = None) -> dict:
        for attempt in range(3):
            resp = self.http.post(API, json={"query": query, "variables": variables or {}}, timeout=60,
                                  headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
            if resp.status_code == 429 and attempt < 2:
                time.sleep(int(resp.headers.get("Retry-After", 30)))
                continue
            break
        if resp.status_code == 429:
            raise BufferError("Buffer rate limit reached. Try again in a few minutes.")
        if resp.status_code in (401, 403):  # the live API answers a bad key with 401 UNAUTHENTICATED
            raise BufferError("Buffer rejected the API key. Create a new one at publish.buffer.com > Settings > API.")
        if resp.status_code >= 400:
            raise BufferError(f"Buffer API HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        if body.get("errors"):
            err = body["errors"][0]
            code = (err.get("extensions") or {}).get("code")
            if code in ("UNAUTHORIZED", "UNAUTHENTICATED"):
                raise BufferError("Buffer rejected the API key. Create a new one at publish.buffer.com > Settings > API.")
            raise BufferError(f"Buffer API: {err.get('message')}" + (f" ({code})" if code else ""))
        return body["data"]

    # ---------- account ----------
    def organization_id(self) -> str:
        if not self._org_id:
            orgs = self.query("query { account { organizations { id name } } }")["account"]["organizations"]
            if not orgs:
                raise BufferError("No Buffer organization found on this account.")
            self._org_id = os.getenv("BUFFER_ORGANIZATION_ID") or orgs[0]["id"]
        return self._org_id

    def channels(self) -> list[dict]:
        q = """query($org: OrganizationId!) { channels(input: {organizationId: $org}) {
                 id name displayName service type descriptor avatar isQueuePaused } }"""
        return self.query(q, {"org": self.organization_id()})["channels"]

    def channel_for(self, platform: str, preferred: str | None = None) -> dict:
        """The Buffer channel to post to for a platform (linkedin/facebook/instagram)."""
        chans = [c for c in self.channels() if c["service"].lower() == platform]
        if not chans:
            raise BufferError(f"No {platform} channel in Buffer. Connect it in Buffer first.")
        if preferred:
            for c in chans:
                if c["id"] == preferred:
                    return c
        return chans[0]

    # ---------- posting ----------
    def create_post(self, channel_id: str, text: str, image_url: str | None = None,
                    due_at: datetime | None = None) -> dict:
        """Schedule at due_at (timezone-aware) or add to the channel's Buffer queue when due_at is None."""
        inp = {"text": text, "channelId": channel_id, "schedulingType": "automatic",
               "mode": "customScheduled" if due_at else "addToQueue",
               "assets": [{"image": {"url": image_url}}] if image_url else []}
        if due_at:
            inp["dueAt"] = due_at.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        q = """mutation($input: CreatePostInput!) { createPost(input: $input) {
                 ... on PostActionSuccess { post { id status dueAt } }
                 ... on MutationError { message } } }"""
        result = self.query(q, {"input": inp})["createPost"]
        if "post" not in result:
            raise BufferError(f"Buffer didn't create the post: {result.get('message', result)}")
        return result["post"]

    # ---------- analytics ----------
    def sent_posts(self, limit: int = 100, channel_ids: list[str] | None = None) -> list[dict]:
        q = """query($org: OrganizationId!, $first: Int, $after: String, $channels: [ChannelId!]) {
                 posts(first: $first, after: $after, input: {organizationId: $org,
                       filter: {status: [sent], channelIds: $channels},
                       sort: [{field: dueAt, direction: desc}]}) {
                   edges { node { id text status sentAt dueAt channelId channelService externalLink
                                  assets { __typename } metrics { type value unit } metricsUpdatedAt } }
                   pageInfo { hasNextPage endCursor } } }"""
        out, after = [], None
        while len(out) < limit:
            data = self.query(q, {"org": self.organization_id(), "first": min(50, limit - len(out)),
                                  "after": after, "channels": channel_ids})["posts"]
            out += [e["node"] for e in data["edges"]]
            if not data["pageInfo"]["hasNextPage"]:
                break
            after = data["pageInfo"]["endCursor"]
        return out

    def sent_posts_frame(self, limit: int = 100) -> pd.DataFrame:
        """Sent posts with metrics, in the project's standard post table."""
        rows = []
        for p in self.sent_posts(limit):
            metrics = {m["type"]: m["value"] for m in (p.get("metrics") or []) if m.get("unit") != "percentage"}
            row = {"post_id": p["id"], "platform": str(p.get("channelService", "")).lower(),
                   "posted_at": p.get("sentAt") or p.get("dueAt"), "text": p.get("text", ""),
                   "media_type": _media_type(p.get("assets") or [])}
            for col, names in METRIC_MAP.items():
                row[col] = next((metrics[n] for n in names if n in metrics), None)
            rows.append(row)
        return to_standard(pd.DataFrame(rows), source="buffer") if rows else pd.DataFrame()


def _media_type(assets: list[dict]) -> str:
    kinds = [a.get("__typename", "").lower() for a in assets]
    if any("video" in k for k in kinds):
        return "video"
    images = sum("image" in k for k in kinds)
    return "carousel" if images > 1 else ("image" if images else "none")


def configured() -> bool:
    return bool(os.getenv("BUFFER_API_KEY"))


def preferred_channels() -> dict:
    """Which Buffer channel to use per platform (chosen on the Connections page, or BUFFER_CHANNEL_<PLATFORM>)."""
    try:
        saved = json.loads(CHANNELS_FILE.read_text())
    except (FileNotFoundError, ValueError):
        saved = {}
    for platform in ("linkedin", "facebook", "instagram"):
        env = os.getenv(f"BUFFER_CHANNEL_{platform.upper()}")
        if env:
            saved[platform] = env
    return saved


def save_preferred_channel(platform: str, channel_id: str) -> None:
    data = preferred_channels()
    data[platform] = channel_id
    CHANNELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHANNELS_FILE.write_text(json.dumps(data, indent=2))
