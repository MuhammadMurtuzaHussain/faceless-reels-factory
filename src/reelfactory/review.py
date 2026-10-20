"""Review lifecycle: what is waiting to render, approve / reject, publish log."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

from . import db
from .paths import AUDIO_EXTS, Paths, load_json

SKELETON_MARK = "WRITE THE SPOKEN SCRIPT"


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def inbox(paths: Paths) -> list[dict]:
    """Every idea with a voiceover in the inbox, and whether it should be rendered now.

    An idea is *ready* when its storyboard is filled in, it is not approved/published,
    it is not rendering, and this exact voiceover has not been rendered before
    (so a failed render is not retried in a loop: re-record or use `retry`).
    """
    out = []
    with db.connect(paths.db) as con:
        for vf in sorted(paths.voiceovers.iterdir()) if paths.voiceovers.exists() else []:
            if vf.name.startswith(".") or not vf.is_file() or vf.suffix.lower() not in AUDIO_EXTS:
                continue
            idea_id = vf.stem
            sb = paths.storyboard(idea_id)
            row = db.get(con, idea_id)
            status = row["status"] if row else "new"
            item = {"id": idea_id, "voiceover": vf.name, "status": status,
                    "title": row["title"] if row else None, "ready": False, "reason": ""}
            if not sb.exists():
                item["reason"] = "no storyboard for this ID"
            elif load_json(sb).get("script", "").startswith(SKELETON_MARK):
                item["reason"] = "storyboard is still the skeleton"
            elif status in db.LOCKED:
                item["reason"] = f"already {status}"
            elif status == "rendering":
                item["reason"] = "rendering now"
            elif row and row["voice_sha1"] == _sha1(vf):
                item["reason"] = f"this voiceover was already rendered ({status})"
            else:
                item["ready"] = True
            out.append(item)
    return out


def approve(paths: Paths, idea_id: str, note: str | None = None) -> dict:
    with db.connect(paths.db) as con:
        row = db.get(con, idea_id)
        if row is None:
            raise ValueError(f"unknown idea {idea_id}")
        if row["status"] != "rendered":
            raise ValueError(f"{idea_id} is {row['status']}; only a rendered video that passed validation can be approved")
        dest = paths.root / "output" / "approved" / idea_id
        dest.mkdir(parents=True, exist_ok=True)
        files = {
            "video": paths.drafts / f"{idea_id}.mp4", "cover": paths.covers / f"{idea_id}.jpg",
            "caption": paths.drafts / f"{idea_id}.caption.txt", "review": paths.drafts / f"{idea_id}.review.md",
            "manifest": paths.manifests / f"{idea_id}.json",
        }
        copied = {}
        for k, src in files.items():
            if src.exists():
                shutil.copy2(src, dest / src.name)
                copied[k] = str(dest / src.name)
        db.set_status(con, idea_id, "approved", review_note=note)
    return {"id": idea_id, "status": "approved", "folder": str(dest), "copied": copied}


def reject(paths: Paths, idea_id: str, note: str | None = None) -> dict:
    with db.connect(paths.db) as con:
        row = db.get(con, idea_id)
        if row is None:
            raise ValueError(f"unknown idea {idea_id}")
        if row["status"] in db.LOCKED:
            raise ValueError(f"{idea_id} is {row['status']}; it can no longer be rejected")
        # clearing voice_sha1 lets the watcher re-render once a new take or storyboard lands
        db.set_status(con, idea_id, "rejected", review_note=note, voice_sha1=None)
    return {"id": idea_id, "status": "rejected", "note": note}


def published(paths: Paths, idea_id: str, url: str) -> dict:
    if not url.startswith(("https://www.instagram.com/", "https://instagram.com/")):
        raise ValueError("expected an https://www.instagram.com/... post URL")
    with db.connect(paths.db) as con:
        row = db.get(con, idea_id)
        if row is None:
            raise ValueError(f"unknown idea {idea_id}")
        if row["status"] not in ("approved", "published"):
            raise ValueError(f"{idea_id} is {row['status']}; approve it before logging it as published")
        ts = db.now()
        db.set_status(con, idea_id, "published", post_url=url, published_at=ts)
    log = paths.root / "output" / "publish-log.csv"
    new = not log.exists()
    with open(log, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["id", "title", "published_at", "post_url", "views", "likes", "comments", "shares", "saves", "notes"])
        w.writerow([idea_id, row["title"], ts, url, "", "", "", "", "", ""])
    return {"id": idea_id, "status": "published", "post_url": url, "log": str(log)}


def jobs(paths: Paths, limit: int = 20) -> list[dict]:
    with db.connect(paths.db) as con:
        rows = con.execute("SELECT id, title, status, attempts, error, review_note, post_url, updated_at FROM ideas "
                           "WHERE id NOT LIKE 'RSS-%' ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def manifest(paths: Paths, idea_id: str) -> dict | None:
    p = paths.manifests / f"{idea_id}.json"
    return json.loads(p.read_text()) if p.exists() else None


# ---------------------------------------------------------------- today's reels (3 a day)

DAILY_SLOTS = 3
STAGES = ("draft", "ready", "voiced", "rendered", "approved", "published")


def stage(paths: Paths, idea_id: str, status: str) -> str:
    """Where a reel is on draft → ready → voiced → rendered → approved → published.

    ``rendered``/``approved``/``published`` come from the database; before that the files decide:
    a voiceover means *voiced*, a filled-in storyboard without ``"draft": true`` means *ready*."""
    if status in ("rendered", "approved", "published"):
        return status
    if paths.find_voiceover(idea_id):
        return "voiced"
    sb = paths.storyboard(idea_id)
    try:
        data = load_json(sb)
    except (OSError, json.JSONDecodeError):
        return "draft"
    script = data.get("script", "").strip()
    if data.get("draft") or not script or script.startswith(SKELETON_MARK):
        return "draft"
    return "ready"


def today(paths: Paths, day: str | None = None) -> list[dict]:
    """Reels started on ``day`` (YYYYMMDD, default today), i.e. IDs ``AI-<day>-NNN``, in ID order."""
    from datetime import date
    day = day or date.today().strftime("%Y%m%d")
    prefix = f"AI-{day}-"
    with db.connect(paths.db) as con:
        rows = {r["id"]: dict(r) for r in con.execute(
            "SELECT id, title, status, attempts, error, review_note, post_url, updated_at FROM ideas "
            "WHERE id LIKE ?", (prefix + "%",))}
    for sb in paths.scripts.glob(prefix + "*.json") if paths.scripts.exists() else []:
        if sb.stem not in rows:                      # a storyboard written before the idea reached the database
            try:
                title = load_json(sb).get("title")
            except (OSError, json.JSONDecodeError):
                title = None
            rows[sb.stem] = {"id": sb.stem, "title": title, "status": "new", "attempts": 0, "error": None,
                             "review_note": None, "post_url": None, "updated_at": None}
    out = []
    for idea_id in sorted(rows):
        r = rows[idea_id]
        r["stage"] = stage(paths, idea_id, r["status"])
        out.append(r)
    return out
