"""Fetch Facebook Page and Instagram Business post metrics from the Meta Graph API.

Setup (one time, done by you):
  1. Create an app at https://developers.facebook.com
  2. Link your Instagram Business/Creator account to a Facebook Page
  3. Get a Page access token with: pages_read_engagement, read_insights,
     instagram_basic, instagram_manage_insights
  4. Put META_PAGE_ID, META_PAGE_ACCESS_TOKEN, META_IG_USER_ID in .env

Meta renames and retires insight metrics fairly often (e.g. Instagram
"impressions" became "views"). Each metric below is requested on its own, so
a retired one is skipped instead of failing the whole run. If numbers come
back empty, check Meta's current docs and update the metric lists.
"""
import os
import time

import pandas as pd
import requests

from ..schema import to_standard

FB_POST_METRICS = {  # Meta metric name -> our column
    "post_impressions": "impressions",
    "post_impressions_unique": "reach",
    "post_clicks": "clicks",
}
IG_MEDIA_METRICS = {
    "views": "impressions",
    "reach": "reach",
    "shares": "shares",
    "saved": "saves",
}


class MetaClient:
    def __init__(self, access_token=None, page_id=None, ig_user_id=None, version=None, session=None):
        self.token = access_token or os.getenv("META_PAGE_ACCESS_TOKEN")
        self.page_id = page_id or os.getenv("META_PAGE_ID")
        self.ig_user_id = ig_user_id or os.getenv("META_IG_USER_ID")
        self.version = version or os.getenv("META_GRAPH_VERSION", "v23.0")
        self.base = f"https://graph.facebook.com/{self.version}"
        self.http = session or requests.Session()
        self.skipped_metrics: set[str] = set()
        if not self.token:
            raise ValueError("No Meta access token. Set META_PAGE_ACCESS_TOKEN in .env.")

    # ---------- low level ----------
    def _get(self, url, params=None):
        params = dict(params or {})
        params["access_token"] = self.token
        for attempt in range(3):
            resp = self.http.get(url, params=params, timeout=30)
            if resp.status_code == 429 or (resp.status_code >= 500 and attempt < 2):
                time.sleep(2 ** attempt * 5)
                continue
            data = resp.json()
            if "error" in data:
                raise MetaAPIError(data["error"])
            return data
        resp.raise_for_status()

    def _paginate(self, path, params, max_items):
        url, items = f"{self.base}/{path}", []
        while url and len(items) < max_items:
            data = self._get(url, params)
            items.extend(data.get("data", []))
            url = data.get("paging", {}).get("next")
            params = None  # the "next" URL already contains the query
        return items[:max_items]

    def _insights(self, object_id, metrics: dict) -> dict:
        out = {}
        for meta_name, col in metrics.items():
            if meta_name in self.skipped_metrics:
                continue
            try:
                data = self._get(f"{self.base}/{object_id}/insights", {"metric": meta_name})
            except MetaAPIError as e:
                if e.code == 100:  # invalid / retired metric for this object
                    self.skipped_metrics.add(meta_name)
                    continue
                raise
            for item in data.get("data", []):
                values = item.get("values") or [{}]
                value = values[0].get("value", item.get("total_value", {}).get("value"))
                if isinstance(value, (int, float)):
                    out[col] = value
        return out

    # ---------- Facebook ----------
    def fetch_facebook_posts(self, max_posts: int = 200) -> pd.DataFrame:
        if not self.page_id:
            raise ValueError("Set META_PAGE_ID in .env.")
        fields = ("id,message,created_time,shares,attachments{media_type},"
                  "reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)")
        posts = self._paginate(f"{self.page_id}/posts", {"fields": fields, "limit": 50}, max_posts)
        rows = []
        for p in posts:
            attachments = p.get("attachments", {}).get("data", [])
            row = {
                "post_id": p["id"],
                "platform": "facebook",
                "posted_at": p.get("created_time"),
                "text": p.get("message", ""),
                "media_type": attachments[0].get("media_type", "none") if attachments else "none",
                "likes": p.get("reactions", {}).get("summary", {}).get("total_count"),
                "comments": p.get("comments", {}).get("summary", {}).get("total_count"),
                "shares": p.get("shares", {}).get("count", 0),
            }
            row.update(self._insights(p["id"], FB_POST_METRICS))
            rows.append(row)
        return to_standard(pd.DataFrame(rows), source="meta_api") if rows else pd.DataFrame()

    # ---------- Instagram ----------
    def fetch_instagram_posts(self, max_posts: int = 200) -> pd.DataFrame:
        if not self.ig_user_id:
            raise ValueError("Set META_IG_USER_ID in .env.")
        fields = "id,caption,media_type,media_product_type,timestamp,like_count,comments_count,permalink"
        media = self._paginate(f"{self.ig_user_id}/media", {"fields": fields, "limit": 50}, max_posts)
        rows = []
        for m in media:
            media_type = m.get("media_type", "IMAGE").lower()
            if m.get("media_product_type") == "REELS":
                media_type = "video"
            row = {
                "post_id": m["id"],
                "platform": "instagram",
                "posted_at": m.get("timestamp"),
                "text": m.get("caption", ""),
                "media_type": media_type,
                "likes": m.get("like_count"),
                "comments": m.get("comments_count"),
            }
            row.update(self._insights(m["id"], IG_MEDIA_METRICS))
            rows.append(row)
        return to_standard(pd.DataFrame(rows), source="meta_api") if rows else pd.DataFrame()

    # ---------- comments ----------
    def list_comments(self, post_id: str, platform: str, limit: int = 25) -> list[dict]:
        if platform == "instagram":
            fields = "id,text,username,timestamp,like_count,replies{id,text,username}"
        else:
            fields = "id,message,from,created_time,like_count,comment_count"
        items = self._paginate(f"{post_id}/comments", {"fields": fields, "limit": limit}, limit)
        return [{
            "comment_id": c["id"],
            "text": c.get("text", c.get("message", "")),
            "author": c.get("username") or c.get("from", {}).get("name"),
            "time": c.get("timestamp") or c.get("created_time"),
            "likes": c.get("like_count"),
            "already_replied": bool(c.get("replies") or c.get("comment_count")),
        } for c in items]

    # ---------- writing (only called by connectors after a human approved the draft) ----------
    def _post(self, path, data):
        data = dict(data)
        data["access_token"] = self.token
        result = self.http.post(f"{self.base}/{path}", data=data, timeout=60).json()
        if "error" in result:
            raise MetaAPIError(result["error"])
        return result

    def publish_facebook_post(self, message: str, scheduled_unix: int | None = None,
                              link: str | None = None) -> str:
        """Publish now, or schedule if scheduled_unix is given (Meta allows 10 minutes to 30 days ahead)."""
        data = {"message": message}
        if link:
            data["link"] = link
        if scheduled_unix:
            data.update(published="false", scheduled_publish_time=str(scheduled_unix))
        return self._post(f"{self.page_id}/feed", data)["id"]

    def publish_instagram_image(self, image_url: str, caption: str) -> str:
        """Instagram needs a PUBLIC image URL. Two steps: create a container, then publish it."""
        container = self._post(f"{self.ig_user_id}/media", {"image_url": image_url, "caption": caption})
        for _ in range(10):  # wait for Meta to process the image
            status = self._get(f"{self.base}/{container['id']}", {"fields": "status_code"})
            if status.get("status_code") == "FINISHED":
                break
            if status.get("status_code") == "ERROR":
                raise MetaAPIError({"code": -1, "message": "Instagram could not process the image."})
            time.sleep(3)
        return self._post(f"{self.ig_user_id}/media_publish", {"creation_id": container["id"]})["id"]

    def reply_to_comment(self, comment_id: str, message: str, platform: str) -> str:
        path = f"{comment_id}/replies" if platform == "instagram" else f"{comment_id}/comments"
        return self._post(path, {"message": message})["id"]

    def fetch_all(self, max_posts: int = 200) -> pd.DataFrame:
        frames = []
        if self.page_id:
            frames.append(self.fetch_facebook_posts(max_posts))
        if self.ig_user_id:
            frames.append(self.fetch_instagram_posts(max_posts))
        frames = [f for f in frames if not f.empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


class MetaAPIError(Exception):
    def __init__(self, error: dict):
        self.code = error.get("code")
        self.error = error
        super().__init__(f"Meta API error {self.code}: {error.get('message')}")
