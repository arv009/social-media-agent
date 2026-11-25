"""The human-in-the-loop review queue (a small SQLite database).

The AI agent can ADD drafts and READ them. Only a human can approve or reject
(in the app's Review queue or scripts/review.py). Publishing tools refuse anything
that isn't approved, so nothing goes public without you.

Two approval steps for posts with a graphic:
  pending (caption review) -> design_review (graphic made, review it) -> approved -> scheduled
Posts without a graphic, and comment replies, go from pending straight to approved.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "review_queue.db"

STATUSES = ["pending", "design_review", "approved", "rejected", "scheduled", "published", "failed"]
KINDS = ["post", "reply"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'post',          -- post | reply
    platform TEXT NOT NULL,                      -- linkedin | facebook | instagram
    text TEXT NOT NULL,
    media_type TEXT DEFAULT 'none',
    image_url TEXT,                              -- public URL of the design (needed for Instagram)
    design_link TEXT,                            -- e.g. Canva edit link, for the reviewer
    suggested_time TEXT,                         -- ISO time, local
    predicted_engagement REAL,
    reply_to_comment_id TEXT,                    -- for replies
    comment_text TEXT,                           -- the comment being replied to (for the reviewer)
    agent_notes TEXT,                            -- why the agent chose this
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer_note TEXT,
    external_id TEXT,                            -- platform id after publishing
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
# Columns added after the first version; added to older databases automatically.
NEW_COLUMNS = {"graphic_spec": "TEXT",      # JSON: layout, headline, label, items, subtext
               "channel_id": "TEXT"}        # Buffer channel the post was scheduled to


@contextmanager
def _conn(db_path=None):
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    have = {r["name"] for r in con.execute("PRAGMA table_info(drafts)")}
    for col, kind in NEW_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE drafts ADD COLUMN {col} {kind}")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def add_draft(platform: str, text: str, kind: str = "post", db_path=None, **fields) -> int:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    allowed = {"media_type", "image_url", "design_link", "suggested_time", "predicted_engagement",
               "reply_to_comment_id", "comment_text", "agent_notes", "graphic_spec"}
    if isinstance(fields.get("graphic_spec"), dict):
        fields["graphic_spec"] = json.dumps(fields["graphic_spec"])
    extra = {k: v for k, v in fields.items() if k in allowed and v is not None}
    cols = ["kind", "platform", "text", "status", "created_at", "updated_at", *extra]
    vals = [kind, platform.lower(), text, "pending", _now(), _now(), *extra.values()]
    with _conn(db_path) as con:
        cur = con.execute(f"INSERT INTO drafts ({', '.join(cols)}) VALUES ({', '.join('?' * len(vals))})", vals)
        return cur.lastrowid


def get_draft(draft_id: int, db_path=None) -> dict | None:
    with _conn(db_path) as con:
        row = con.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        return dict(row) if row else None


def list_drafts(status: str | None = None, kind: str | None = None, limit: int = 50, db_path=None) -> list[dict]:
    q, args = "SELECT * FROM drafts WHERE 1=1", []
    if status:
        q += " AND status = ?"
        args.append(status)
    if kind:
        q += " AND kind = ?"
        args.append(kind)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _conn(db_path) as con:
        return [dict(r) for r in con.execute(q, args).fetchall()]


def update_draft_text(draft_id: int, text: str, db_path=None) -> None:
    """Agent revisions are only allowed while a draft is still pending or was rejected."""
    with _conn(db_path) as con:
        row = con.execute("SELECT status FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if not row:
            raise ValueError(f"Draft {draft_id} not found")
        if row["status"] not in ("pending", "rejected"):
            raise ValueError(f"Draft {draft_id} is {row['status']}; it can't be edited anymore")
        con.execute("UPDATE drafts SET text = ?, status = 'pending', updated_at = ? WHERE id = ?",
                    (text, _now(), draft_id))


# ---------- human-only actions (NOT exposed as agent tools) ----------

def review(draft_id: int, approve: bool, note: str | None = None, db_path=None) -> None:
    with _conn(db_path) as con:
        con.execute("UPDATE drafts SET status = ?, reviewer_note = ?, updated_at = ? WHERE id = ?",
                    ("approved" if approve else "rejected", note, _now(), draft_id))


def human_edit(draft_id: int, text: str | None = None, suggested_time: str | None = None, db_path=None) -> None:
    """The reviewer's own edits. Allowed until the draft is published or scheduled."""
    with _conn(db_path) as con:
        row = con.execute("SELECT status FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if not row or row["status"] in ("published", "scheduled"):
            raise ValueError(f"Draft {draft_id} can't be edited.")
        if text is not None:
            con.execute("UPDATE drafts SET text = ?, updated_at = ? WHERE id = ?", (text, _now(), draft_id))
        if suggested_time is not None:
            con.execute("UPDATE drafts SET suggested_time = ?, updated_at = ? WHERE id = ?",
                        (suggested_time, _now(), draft_id))


def send_back_to_pending(draft_id: int, db_path=None) -> None:
    with _conn(db_path) as con:
        con.execute("UPDATE drafts SET status = 'pending', updated_at = ? WHERE id = ? AND status IN "
                    "('approved', 'rejected', 'failed', 'design_review')", (_now(), draft_id))


def counts(db_path=None) -> dict:
    with _conn(db_path) as con:
        rows = con.execute("SELECT status, COUNT(*) AS n FROM drafts GROUP BY status").fetchall()
    return {s: 0 for s in STATUSES} | {r["status"]: r["n"] for r in rows}


# ---------- used by publishing connectors ----------

def require_approved(draft_id: int, kind: str, db_path=None) -> dict:
    draft = get_draft(draft_id, db_path)
    if not draft:
        raise PermissionError(f"Draft {draft_id} not found.")
    if draft["kind"] != kind:
        raise PermissionError(f"Draft {draft_id} is a {draft['kind']}, not a {kind}.")
    if draft["status"] != "approved":
        raise PermissionError(f"Draft {draft_id} is '{draft['status']}'. Only approved drafts can be published; "
                              "a human must approve it first.")
    return draft


def mark_done(draft_id: int, status: str, external_id: str | None = None, db_path=None) -> None:
    with _conn(db_path) as con:
        con.execute("UPDATE drafts SET status = ?, external_id = COALESCE(?, external_id), updated_at = ? "
                    "WHERE id = ?", (status, external_id, _now(), draft_id))


def graphic_spec(draft: dict) -> dict | None:
    try:
        return json.loads(draft["graphic_spec"]) if draft.get("graphic_spec") else None
    except (TypeError, ValueError):
        return None


def needs_graphic(draft: dict) -> bool:
    return draft["kind"] == "post" and bool(draft.get("image_url") or draft.get("graphic_spec"))


def set_graphic(draft_id: int, image_url: str, spec: dict | None = None, db_path=None) -> None:
    """Attach a (re)generated graphic and move the draft to graphic review (human-triggered)."""
    with _conn(db_path) as con:
        con.execute("UPDATE drafts SET image_url = ?, graphic_spec = COALESCE(?, graphic_spec), "
                    "status = 'design_review', updated_at = ? WHERE id = ?",
                    (image_url, json.dumps(spec) if spec else None, _now(), draft_id))


def set_status(draft_id: int, status: str, note: str | None = None, db_path=None) -> None:
    """Human-only status change (used by the app's review buttons)."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    with _conn(db_path) as con:
        con.execute("UPDATE drafts SET status = ?, reviewer_note = COALESCE(?, reviewer_note), updated_at = ? "
                    "WHERE id = ?", (status, note, _now(), draft_id))


def set_publish_result(draft_id: int, status: str, external_id: str | None = None, channel_id: str | None = None,
                       image_url: str | None = None, db_path=None) -> None:
    with _conn(db_path) as con:
        con.execute("UPDATE drafts SET status = ?, external_id = COALESCE(?, external_id), "
                    "channel_id = COALESCE(?, channel_id), image_url = COALESCE(?, image_url), updated_at = ? "
                    "WHERE id = ?", (status, external_id, channel_id, image_url, _now(), draft_id))
