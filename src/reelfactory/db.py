"""SQLite storage for ideas, render jobs and their status."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS ideas (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    summary       TEXT,
    source_url    TEXT,
    source_name   TEXT,
    published_at  TEXT,
    discovered_at TEXT,
    url_key       TEXT UNIQUE,
    title_key     TEXT,
    score         REAL,
    score_breakdown TEXT,
    status        TEXT NOT NULL DEFAULT 'new',
    script_path   TEXT,
    voiceover_path TEXT,
    output_path   TEXT,
    error         TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS ideas_status ON ideas(status);
CREATE INDEX IF NOT EXISTS ideas_title_key ON ideas(title_key);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# columns added after the first release; created on demand so old databases keep working
MIGRATIONS = {
    "voice_sha1": "TEXT",        # sha1 of the voiceover last rendered (inbox watcher uses it)
    "review_note": "TEXT",
    "post_url": "TEXT",
    "published_at": "TEXT",
}

# lifecycle: discovered -> used (RSS item) | selected -> rendering -> rendered | failed
#            rendered -> approved | rejected ; approved -> published
LOCKED = ("approved", "published")


@contextmanager
def connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    have = {r["name"] for r in con.execute("PRAGMA table_info(ideas)")}
    for col, typ in MIGRATIONS.items():
        if col not in have:
            con.execute(f"ALTER TABLE ideas ADD COLUMN {col} {typ}")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def upsert_idea(con, idea_id: str, title: str, **fields) -> None:
    fields = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in fields.items()}
    fields["updated_at"] = now()
    row = con.execute("SELECT id FROM ideas WHERE id=?", (idea_id,)).fetchone()
    if row:
        sets = ", ".join(f"{k}=?" for k in ["title", *fields])
        con.execute(f"UPDATE ideas SET {sets} WHERE id=?", (title, *fields.values(), idea_id))
    else:
        cols = ["id", "title", *fields]
        con.execute(f"INSERT INTO ideas ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    (idea_id, title, *fields.values()))


def set_status(con, idea_id: str, status: str, error: str | None = None, bump_attempt: bool = False, **fields) -> None:
    fields.update(status=status, error=error, updated_at=now())
    sets = ", ".join(f"{k}=?" for k in fields)
    extra = ", attempts = attempts + 1" if bump_attempt else ""
    con.execute(f"UPDATE ideas SET {sets}{extra} WHERE id=?", (*fields.values(), idea_id))


def get(con, idea_id: str):
    return con.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()


def next_id(con, day: str) -> str:
    prefix = f"AI-{day}-"
    rows = con.execute("SELECT id FROM ideas WHERE id LIKE ?", (prefix + "%",)).fetchall()
    nums = [int(r["id"].rsplit("-", 1)[1]) for r in rows if r["id"].rsplit("-", 1)[1].isdigit()]
    return f"{prefix}{(max(nums) + 1) if nums else 1:03d}"
