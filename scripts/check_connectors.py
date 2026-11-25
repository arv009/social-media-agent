"""Show which connectors are connected and what tools they offer. No API key needed.

    python scripts/check_connectors.py           # status + tool list
    python scripts/check_connectors.py --smoke   # also call a few safe, read-only tools
"""
import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_agent.agent import ConnectorHub  # noqa: E402

SMOKE_CALLS = [
    ("performance_summary", {}),
    ("score_drafts", {"drafts_json": '[{"label": "question + carousel", "platform": "linkedin", '
                      '"media_type": "carousel", "text": "Honestly, I made every mistake in the book. '
                      'Here are 5 lessons, step by step. Which one would you try first? #marketing"}, '
                      '{"label": "promo + link", "platform": "linkedin", "media_type": "image", '
                      '"text": "Big sale: 20% off! Shop now https://example.com"}]'}),
    ("list_drafts", {"limit": 3}),
]


async def main(smoke: bool):
    async with ConnectorHub() as hub:
        print("Connectors\n" + "-" * 60)
        print(hub.status_table())
        for s in hub.status:
            if s.tools:
                print(f"\n{s.name}: {', '.join(s.tools)}")
        if smoke:
            print("\nSmoke test\n" + "-" * 60)
            for name, args in SMOKE_CALLS:
                text, is_error = await hub.call(name, args)
                print(f"\n> {name}{' (ERROR)' if is_error else ''}\n{text[:800]}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true")
    asyncio.run(main(p.parse_args().smoke))
