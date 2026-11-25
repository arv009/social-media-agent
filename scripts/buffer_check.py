"""Check your Buffer (and Cloudinary) setup. Read-only: nothing is posted.

    python scripts/buffer_check.py

Lists your Buffer channels and your 5 most recent published posts with their metrics.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from social_agent import buffer_api, image_host  # noqa: E402


def main():
    try:
        client = buffer_api.BufferClient()
        print(f"Buffer organization: {client.organization_id()}")
        chans = client.channels()
    except buffer_api.BufferError as e:
        sys.exit(f"Buffer: {e}")
    print(f"\n{len(chans)} channel(s):")
    for c in chans:
        print(f"  {c['service']:<10} {c.get('displayName') or c.get('name'):<30} {c.get('descriptor') or c.get('type')}"
              f"   id={c['id']}")
    try:
        df = client.sent_posts_frame(limit=5)
        print(f"\nRecent published posts: {len(df)}")
        if not df.empty:
            print(df[["posted_at", "platform", "impressions", "likes", "comments", "shares"]].to_string(index=False))
    except buffer_api.BufferError as e:
        print(f"\nCouldn't read posts/metrics: {e}")
    print("\nCloudinary:", "configured" if image_host.configured() else "not set up (needed for images)")


if __name__ == "__main__":
    main()
