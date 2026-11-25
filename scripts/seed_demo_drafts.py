"""Add a few example drafts to the review queue, to try the review page without a Claude API key.

    python scripts/seed_demo_drafts.py           # add demo drafts
    python scripts/seed_demo_drafts.py --clear   # remove them again
"""
import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_agent import graphics  # noqa: E402
from social_agent import review_queue as rq  # noqa: E402

TAG = "[demo] "


def next_weekday(weekday: int, hour: int) -> str:
    d = datetime.now() + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat(timespec="minutes")


DEMO = [
    dict(platform="linkedin", media_type="carousel", predicted_engagement=0.071,
         suggested_time=next_weekday(1, 9),
         agent_notes="Personal story + question scored highest of 3 variants; Tue 9 AM is the best LinkedIn slot.",
         text=("Honestly, I used to think posting every day was the secret to growing on LinkedIn.\n\n"
               "I was wrong. Here are 5 lessons that doubled our reach this year, step by step:\n\n"
               "1. Post 3x a week, not 7\n2. Lead with a story, not a pitch\n3. Carousels beat plain text\n"
               "4. Reply to every comment in the first hour\n5. Save links for the comments\n\n"
               "Which one would you try first?\n\n#marketing #smallbusiness #linkedintips")),
    dict(platform="instagram", media_type="image", predicted_engagement=0.094,
         graphic=("Meet the team behind every post", "A peek behind the scenes at our office", "bold"),
         suggested_time=next_weekday(4, 19),
         agent_notes="Behind-the-scenes posts are the best Instagram topic for this account; evenings perform best.",
         text=("Behind the scenes at our office today ✨ Meet the team that plans every post you see here.\n\n"
               "What would you like to see more of? 👇\n\n#behindthescenes #smallbusiness #teamwork "
               "#marketing #contentcreator")),
    dict(platform="facebook", media_type="image", predicted_engagement=0.031,
         graphic=("Free webinar: social media on a small budget", "Next Thursday, 7 PM. Register now.", "accent"),
         suggested_time=next_weekday(2, 12),
         agent_notes="Event posts do slightly below average; midday Wednesday is the strongest Facebook slot.",
         text=("Join us for a free webinar next Thursday at 7 PM: \"Social media on a small budget\". "
               "We'll share the exact plan we use every month. Register now, link in the comments!")),
]
DEMO_REPLY = dict(platform="facebook", comment_id="demo_comment_1",
                  comment_text="Is the webinar recorded? I can't make it on Thursday 😕",
                  reply_text=("Great question! Yes, everyone who registers gets the recording by email the next "
                              "day. Hope it helps! 😊"),
                  agent_notes="Friendly, answers the question, no promises beyond what the event offers.")


def clear_demo() -> int:
    with sqlite3.connect(rq.DB_PATH) as con:
        return con.execute("DELETE FROM drafts WHERE agent_notes LIKE ?", (TAG + "%",)).rowcount


def seed_demo() -> int:
    rq.list_drafts(limit=1)  # makes sure the database and table exist
    for d in DEMO:
        d = dict(d)
        text, notes = d.pop("text"), TAG + d.pop("agent_notes")
        if "graphic" in d:
            headline, sub, style = d.pop("graphic")
            path = graphics.make_post_graphic(headline, sub, d["platform"], style)
            d["image_url"] = str(path.relative_to(ROOT))
        rq.add_draft(d.pop("platform"), text, kind="post", agent_notes=notes, **d)
    r = DEMO_REPLY
    rq.add_draft(r["platform"], r["reply_text"], kind="reply", reply_to_comment_id=r["comment_id"],
                 comment_text=r["comment_text"], agent_notes=TAG + r["agent_notes"])
    return len(DEMO) + 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--clear", action="store_true")
    args = p.parse_args()
    if args.clear:
        print(f"Removed {clear_demo()} demo drafts.")
        return
    print(f"Added {seed_demo()} demo drafts. Open the review page: streamlit run app/review_app.py")


if __name__ == "__main__":
    main()
