"""Human review of drafts the agent created. (A Streamlit page will replace this later.)

    python scripts/review.py                 # walk through pending drafts
    python scripts/review.py --list all      # show drafts of any status
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_agent import review_queue as rq  # noqa: E402


def show(d: dict):
    print("=" * 70)
    print(f"#{d['id']}  {d['kind'].upper()} for {d['platform']}  [{d['status']}]  created {d['created_at']}")
    if d["kind"] == "reply":
        print(f"Replying to comment: {d['comment_text']!r}")
    if d["suggested_time"]:
        print(f"Suggested time: {d['suggested_time']}")
    if d["predicted_engagement"] is not None:
        print(f"Predicted engagement: {d['predicted_engagement']:.2%}")
    if d["design_link"] or d["image_url"]:
        print(f"Design: {d['design_link'] or d['image_url']}")
    if d["agent_notes"]:
        print(f"Agent notes: {d['agent_notes']}")
    print("-" * 70)
    print(d["text"])
    print("-" * 70)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--list", choices=["all", *rq.STATUSES])
    args = p.parse_args()

    if args.list:
        for d in rq.list_drafts(status=None if args.list == "all" else args.list, limit=100):
            print(f"#{d['id']:<4} {d['status']:<10} {d['kind']:<6} {d['platform']:<10} {d['text'][:60]!r}")
        return

    pending = list(reversed(rq.list_drafts(status="pending", limit=100)))
    if not pending:
        print("No pending drafts.")
        return
    for d in pending:
        show(d)
        choice = input("[a]pprove, [r]eject, [s]kip, [q]uit? ").strip().lower()
        if choice == "a":
            rq.review(d["id"], approve=True)
            print(f"✅ #{d['id']} approved. Ask the agent to publish it, e.g. 'publish draft {d['id']}'.")
        elif choice == "r":
            note = input("What should change? (the agent reads this) ").strip()
            rq.review(d["id"], approve=False, note=note or None)
            print(f"❌ #{d['id']} rejected.")
        elif choice == "q":
            break


if __name__ == "__main__":
    main()
