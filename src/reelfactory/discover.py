"""RSS discovery, deduplication, transparent ranking and the daily shortlist."""
from __future__ import annotations

import hashlib
import html
import json
import logging
import math
import re
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

from . import db
from .paths import Paths, load_json, load_style

log = logging.getLogger(__name__)
UA = "reelfactory/0.1 (+local personal RSS reader)"
STOP = set("the a an and or of to in on for with is are was be by at as from this that it its into how why what "
           "your you new after over about says said will can now just more than their".split())


# ---------------------------------------------------------------- normalisation


def canonical_url(url: str) -> str:
    s = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(s.query) if not k.lower().startswith(("utm_", "ref", "fbclid", "gclid"))]
    path = s.path.rstrip("/") or "/"
    return urlunsplit((s.scheme.lower() or "https", s.netloc.lower().removeprefix("www."), path, urlencode(q), ""))


def title_tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9$]+", title.lower()) if w not in STOP and len(w) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def clean_summary(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()[:500]


def entry_time(e) -> datetime | None:
    for k in ("published_parsed", "updated_parsed"):
        t = e.get(k)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


# ---------------------------------------------------------------- discovery


def fetch(feed: dict) -> tuple[dict, list, str | None]:
    try:
        d = feedparser.parse(feed["url"], agent=UA)
        status = d.get("status", 0)
        if status >= 400 or (not d.entries and d.get("bozo")):
            return feed, [], f"HTTP {status} {d.get('bozo_exception', '')}".strip()
        return feed, d.entries, None
    except Exception as e:  # network errors must not kill the run
        return feed, [], f"{type(e).__name__}: {e}"


def discover(paths: Paths) -> dict:
    cfg = load_json(paths.feeds_file)
    socket.setdefaulttimeout(20)
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.get("max_age_days", 3))
    stats = {"feeds": 0, "failed": [], "seen": 0, "new": 0, "dupes": 0}
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(fetch, cfg["feeds"]))
    with db.connect(paths.db) as con:
        recent = con.execute("SELECT title_key FROM ideas WHERE discovered_at >= ?",
                             ((datetime.now(timezone.utc) - timedelta(days=14)).isoformat(),)).fetchall()
        recent_tokens = [set(r["title_key"].split()) for r in recent if r["title_key"]]
        for feed, entries, err in results:
            stats["feeds"] += 1
            if err:
                stats["failed"].append(f"{feed['name']}: {err}")
                log.warning("feed failed: %s (%s)", feed["name"], err)
                continue
            for e in entries[: cfg.get("max_entries_per_feed", 40)]:
                link, title = e.get("link"), html.unescape(e.get("title", "")).strip()
                ts = entry_time(e)
                if not link or not title or (ts and ts < cutoff):
                    continue
                stats["seen"] += 1
                url = canonical_url(link)
                url_key = hashlib.sha1(url.encode()).hexdigest()
                if con.execute("SELECT 1 FROM ideas WHERE url_key=?", (url_key,)).fetchone():
                    stats["dupes"] += 1
                    continue
                toks = title_tokens(title)
                if any(jaccard(toks, t) >= 0.75 for t in recent_tokens):
                    stats["dupes"] += 1            # same story syndicated elsewhere; keep first copy
                    continue
                recent_tokens.append(toks)
                db.upsert_idea(con, f"RSS-{url_key[:10]}", title, summary=clean_summary(e.get("summary", "")),
                               source_url=link, source_name=feed["name"],
                               published_at=ts.isoformat() if ts else None, discovered_at=db.now(),
                               url_key=url_key, title_key=" ".join(sorted(toks)), status="discovered")
                stats["new"] += 1
    log.info("discover: %s", stats)
    return stats


# ---------------------------------------------------------------- ranking


def term_hits(text: str, terms) -> list[str]:
    out = []
    for t in terms:
        if re.fullmatch(r"[\w ]+", t):
            if re.search(rf"\b{re.escape(t)}\b", text):
                out.append(t)
        elif t in text:
            out.append(t)
    return out


def score_item(row, cfg: dict, feed_weights: dict, others: list[set[str]], made: list[set[str]],
               now: datetime) -> dict:
    rk = cfg["ranking"]
    text = f"{row['title']} {row['summary'] or ''}".lower()
    title = row["title"].lower()
    toks = set((row["title_key"] or "").split())
    pub = datetime.fromisoformat(row["published_at"]) if row["published_at"] else now - timedelta(hours=24)
    age_h = max((now - pub).total_seconds() / 3600, 0)
    rel_hits = term_hits(text, rk["relevance_terms"])
    hook_hits = term_hits(title, rk["hook_terms"])
    fam = [name for name, terms in rk["visual_families"].items() if term_hits(text, terms)]
    sims = [jaccard(toks, o) for o in others]
    f = {
        "freshness": math.exp(-age_h / 24),
        "relevance": min(1.0, sum(rk["relevance_terms"][h] for h in rel_hits) / 1.5),
        "novelty": 1 - max((jaccard(toks, m) for m in made), default=0.0),
        "momentum": min(1.0, sum(1 for s in sims if s >= 0.3) / 2),
        "hook": min(1.0, len(hook_hits) / 2 + (0.3 if re.search(r"\d", title) else 0) + (0.2 if "?" in title else 0)),
        "visual": 1.0 if fam else 0.4,
    }
    total = sum(rk["weights"][k] * v for k, v in f.items()) * 100 * feed_weights.get(row["source_name"], 1.0)
    return {"score": round(total, 1), "factors": {k: round(v, 2) for k, v in f.items()},
            "age_hours": round(age_h, 1), "relevance_hits": rel_hits, "hook_hits": hook_hits, "visual_families": fam}


def rank(paths: Paths) -> int:
    cfg = load_json(paths.feeds_file)
    fw = {f["name"]: f.get("weight", 1.0) for f in cfg["feeds"]}
    now = datetime.now(timezone.utc)
    with db.connect(paths.db) as con:
        rows = con.execute("SELECT * FROM ideas WHERE status='discovered'").fetchall()
        made = [title_tokens(r["title"]) for r in con.execute(
            "SELECT title FROM ideas WHERE id LIKE 'AI-%' AND updated_at >= ?",
            ((now - timedelta(days=14)).isoformat(),)).fetchall()]
        all_toks = {r["id"]: set((r["title_key"] or "").split()) for r in rows}
        for r in rows:
            others = [t for i, t in all_toks.items() if i != r["id"] and r["source_name"]]
            s = score_item(r, cfg, fw, others, made, now)
            con.execute("UPDATE ideas SET score=?, score_breakdown=? WHERE id=?", (s["score"], json.dumps(s), r["id"]))
    log.info("ranked %d items", len(rows))
    return len(rows)


# ---------------------------------------------------------------- shortlist + briefs

BRIEF = """You are helping me write a 20–30 second Instagram Reel for {handle} ({niche}).

Topic: {title}
Source: {url} ({source})
Summary from the feed: {summary}

Please:
1. Open and read the source. List the 3–5 key facts, each with the exact supporting quote/URL. Mark anything you could not verify as UNCERTAIN.
2. Write 3 hook options (first line, under 10 words).
3. Write a spoken script of 55–75 words: hook, 2–3 beats, one-line takeaway. Only use verified facts; no hype; plain English.
4. Turn the script into an animated STORY storyboard (fill in the JSON below; the full reference is docs/story-scenes.md).
   The video must SHOW the story, not print it: characters act out each beat (a bean person or an AI-agent bot,
   with moods, poses, speech bubbles and emotes), objects appear and change as the voice mentions them, and the
   camera pushes in on the key moment. The spoken words already appear as big kinetic captions at the top, so
   don't repeat sentences on screen: use short labels, counters, stamps or one `title` punchline instead.
   - One `story` scene per beat (5–7 scenes). Each picks a `set`: island, stage, night, office, lab, city, cyber or room.
   - Define recurring characters once in `cast` (kind person|bot, color, outfit, name) and keep them across scenes.
   - Elements: actor, prop, swarm, grid, counter, label, stamp, link, crowd, confetti. Every scene needs motion
     on cues: `at` to appear, `out_at` to leave, and `do` entries ({{"at": cue, "move"/"pose"/"mood"/"say"/"emote"/"state"/"value": …}}).
   - Moods: neutral happy grin smirk sly shock sad worried focused sleepy proud curious angry.
     Poses: idle wave cheer point present type hold think shrug relax panic cross juggle throw catch hips (add -left to mirror).
     Props: palm block ball hoop clock note window terminal laptop desk building server mountain flag sign lamp bulb
     magnifier lock shield trophy chart meter lava rock star phone podium plant tower.
   - Stage: x 0–1080 (or left / center / right…), ground y ≈ 1340; keep labels above y 1450 and nothing important above y 480.
   - Every `at` / `*_at` value must be an exact phrase from the script (or a number of seconds into the scene).
   - Illustrative visuals (e.g. bar heights, block counts) must not suggest numbers the source doesn't give; note them in `claims`.
5. Don't end the script with "follow me": a spoken call to action and a Follow end card are added automatically.
6. Fill `thumbnail`: the Reel cover. A short, curiosity-driven line (3–7 words, readable at phone-grid size), not the first
   headline repeated, plus the main character (`actor`) and `set`.

{skeleton}
"""


def shortlist(paths: Paths, size: int | None = None) -> Path:
    cfg = load_json(paths.feeds_file)
    size = size or cfg.get("shortlist_size", 5)
    with db.connect(paths.db) as con:
        rows = con.execute("SELECT * FROM ideas WHERE status='discovered' AND score IS NOT NULL "
                           "ORDER BY score DESC LIMIT 200").fetchall()
    picked, seen, per_source = [], [], {}
    for r in rows:                          # skip near-duplicate stories already picked
        toks = set((r["title_key"] or "").split())
        if any(jaccard(toks, s) >= 0.4 for s in seen):
            continue
        if per_source.get(r["source_name"], 0) >= cfg.get("max_per_source", 2):
            continue
        per_source[r["source_name"]] = per_source.get(r["source_name"], 0) + 1
        seen.append(toks)
        picked.append(r)
        if len(picked) == size:
            break
    day = datetime.now().strftime("%Y-%m-%d")
    md = [f"# Daily shortlist {day}", "",
          "Pick one, then run `python -m reelfactory new-idea <rank>`. Scores are heuristics, not judgement: "
          "check each source yourself.", "",
          "| # | Score | Title | Source | Age |", "|---|---|---|---|---|"]
    top = cfg.get("top_picks", 3)
    for i, r in enumerate(picked, 1):
        b = json.loads(r["score_breakdown"])
        star = "⭐ " if i <= top else ""
        md.append(f"| {star}{i} | {r['score']:.0f} | [{r['title'].replace('|', '/')}]({r['source_url']}) | {r['source_name']} | {b['age_hours']:.0f}h |")
    for i, r in enumerate(picked, 1):
        b = json.loads(r["score_breakdown"])
        md += ["", f"## {i}. {r['title']}", f"- Source: {r['source_url']}", f"- ID: `{r['id']}`",
               "- Score breakdown: " + ", ".join(f"{k} {v}" for k, v in b["factors"].items()),
               f"- Relevance terms: {', '.join(b['relevance_hits']) or '—'}; hook terms: {', '.join(b['hook_hits']) or '—'}; "
               f"visual fit: {', '.join(b['visual_families']) or 'generic'}",
               f"- Summary: {r['summary'] or '—'}"]
    out = paths.scripts / f"shortlist-{day}.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    (paths.scripts / f"shortlist-{day}.json").write_text(json.dumps([r["id"] for r in picked]))
    return out


def latest_shortlist(paths: Paths) -> list[dict]:
    """The most recent shortlist as plain dicts (rank, id, title, url, source, score, top)."""
    lists = sorted(paths.scripts.glob("shortlist-*.json"))
    if not lists:
        return []
    ids = json.loads(lists[-1].read_text())
    top = load_json(paths.feeds_file).get("top_picks", 3)
    out = []
    with db.connect(paths.db) as con:
        for rank, i in enumerate(ids, 1):
            r = db.get(con, i)
            if r:
                out.append({"rank": rank, "id": r["id"], "title": r["title"], "url": r["source_url"],
                            "source": r["source_name"], "score": r["score"], "top": rank <= top,
                            "status": r["status"], "date": lists[-1].stem.removeprefix("shortlist-")})
    return out


def account(paths: Paths) -> tuple[str, str]:
    """(handle, niche) from style.json, used in briefs and caption drafts."""
    style = load_style(paths)
    return style.get("handle", "@yourhandle"), style.get("niche", "AI & tech, explained simply")


def skeleton(idea_id: str, row, handle: str = "@yourhandle", niche: str = "AI & tech, explained simply") -> dict:
    return {
        "id": idea_id,
        "title": row["title"],
        "theme": "story",
        "script": "WRITE THE SPOKEN SCRIPT HERE (55-75 words).",
        "emphasis": ["word1", "word2"],
        "cast": {
            "agent": {"kind": "bot", "color": "accent", "name": "Agent"},
            "person": {"kind": "person", "color": "slate", "outfit": ["glasses"]},
        },
        "scenes": [
            {"type": "story", "at": "first two words of the script", "params": {
                "set": "stage",
                "camera": {"moves": [{"at": "cue phrase", "zoom": 1.2, "focus": "agent1", "dur": 0.8}]},
                "elements": [
                    {"el": "actor", "who": "person", "id": "person1", "x": 300, "enter": "walk-left", "mood": "curious",
                     "do": [{"at": "cue phrase", "pose": "point", "emote": "!"}]},
                    {"el": "actor", "who": "agent", "id": "agent1", "x": 760, "enter": "drop", "at": "cue phrase",
                     "label": True, "do": [{"at": "cue phrase", "mood": "happy", "say": "Short line"}]},
                    {"el": "label", "text": "short tag", "x": 540, "y": 1440, "at": "cue phrase"}]}},
            {"type": "story", "at": "exact phrase", "params": {
                "set": "cyber", "transition": "whip",
                "elements": [
                    {"el": "grid", "id": "sites", "x": 540, "y": 800, "count": 60, "cols": 10, "w": 640,
                     "fill_at": "cue phrase", "end_at": "cue phrase", "label": "examples"},
                    {"el": "swarm", "who": "agent", "from": [540, 1300], "to": "sites", "count": 10, "at": "cue phrase"},
                    {"el": "counter", "x": 540, "y": 1250, "to": 100, "suffix": "+", "at": "cue phrase", "label": "label"}]}},
            {"type": "story", "at": "exact phrase", "params": {
                "set": "room", "transition": "zoom",
                "title": {"text": "Final *question?*", "at": "cue phrase"},
                "elements": [
                    {"el": "prop", "kind": "note", "x": 620, "y": 900, "title": "file.txt", "lines": ["line one", "line two"],
                     "mark": 0, "mark_at": "cue phrase"},
                    {"el": "actor", "who": "agent", "x": 290, "do": [{"at": "cue phrase", "mood": "sly", "pose": "shrug"}]}]}},
        ],
        "thumbnail": {"label": "2-3 word tag", "headline": "3-7 word cover line with *one accent phrase*",
                      "set": "stage", "actor": {"who": "agent", "mood": "grin", "pose": "cheer"}},
        "claims": [{"text": "claim", "status": "verified|uncertain|general", "note": "quote + URL"}],
        "sources": [{"title": row["title"], "url": row["source_url"]}],
        "caption": {"hook": "", "body": "", "cta": f"Follow {handle} for more {niche}.",
                    "hashtags": ["#ai", "#tech"]},
    }


def idea_file(paths: Paths, pick: str) -> Path | None:
    """``pick`` as one of your own idea notes: a path to a .md file, or a name in inbox/ideas/."""
    if not pick.lower().endswith(".md"):
        return None
    for p in (Path(pick).expanduser(), paths.ideas_inbox / pick):
        if p.is_file():
            return p
    raise SystemExit(f"idea file not found: {pick} (put it in {paths.ideas_inbox})")


def parse_note(text: str, fallback_title: str) -> dict:
    """Title, source links and notes from a markdown idea."""
    lines = [ln.strip() for ln in text.splitlines()]
    heads = [ln.lstrip("#").strip() for ln in lines if ln.startswith("#")]
    first = next((ln for ln in lines if ln), "")
    title = heads[0] if heads else (first[:90] if first else fallback_title)
    urls = list(dict.fromkeys(u.rstrip(").,>]") for u in re.findall(r"https?://\S+", text)))
    return {"title": title, "urls": urls, "notes": text.strip()[:4000]}


def ideas_waiting(paths: Paths) -> list[Path]:
    return sorted(p for p in paths.ideas_inbox.glob("*.md")) if paths.ideas_inbox.exists() else []


def new_idea_from_note(paths: Paths, note: Path) -> tuple[str, Path, Path]:
    n = parse_note(note.read_text(encoding="utf-8"), note.stem.replace("-", " ").replace("_", " "))
    row = {"title": n["title"], "source_url": n["urls"][0] if n["urls"] else None}
    with db.connect(paths.db) as con:
        idea_id = db.next_id(con, datetime.now().strftime("%Y%m%d"))
        handle, niche = account(paths)
        sk = skeleton(idea_id, row, handle, niche)
        sk["sources"] = [{"title": n["title"], "url": u} for u in n["urls"]] or [{"title": "", "url": ""}]
        sb_path = paths.storyboard(idea_id)
        sb_path.write_text(json.dumps(sk, indent=2), encoding="utf-8")
        brief = paths.scripts / f"{idea_id}.brief.md"
        src = ", ".join(n["urls"]) if n["urls"] else "none given: find a reliable source for every fact you use"
        brief.write_text(BRIEF.format(handle=handle, niche=niche, title=n["title"], url=src,
                                      source=f"my notes, {note.name}", summary="\n\n" + n["notes"] + "\n", skeleton=json.dumps(sk, indent=2)),
                         encoding="utf-8")
        db.upsert_idea(con, idea_id, n["title"], source_url=row["source_url"], source_name="my notes",
                       status="selected", script_path=str(sb_path))
    if note.parent.resolve() == paths.ideas_inbox.resolve():  # filed away so it isn't picked twice
        used = paths.ideas_inbox / "used"
        used.mkdir(exist_ok=True)
        note.replace(used / f"{idea_id}-{note.name}")
    return idea_id, sb_path, brief


def new_idea(paths: Paths, pick: str) -> tuple[str, Path, Path]:
    note = idea_file(paths, pick)
    if note is not None:
        return new_idea_from_note(paths, note)
    with db.connect(paths.db) as con:
        if pick.isdigit():
            lists = sorted(paths.scripts.glob("shortlist-*.json"))
            if not lists:
                raise SystemExit("no shortlist yet: run `python -m reelfactory daily` first")
            ids = json.loads(lists[-1].read_text())
            if not 1 <= int(pick) <= len(ids):
                raise SystemExit(f"pick 1..{len(ids)}")
            src_id = ids[int(pick) - 1]
        else:
            src_id = pick
        row = db.get(con, src_id)
        if row is None:
            raise SystemExit(f"unknown item {src_id}")
        idea_id = db.next_id(con, datetime.now().strftime("%Y%m%d"))
        handle, niche = account(paths)
        sk = skeleton(idea_id, row, handle, niche)
        sb_path = paths.storyboard(idea_id)
        sb_path.write_text(json.dumps(sk, indent=2), encoding="utf-8")
        brief = paths.scripts / f"{idea_id}.brief.md"
        brief.write_text(BRIEF.format(handle=handle, niche=niche, title=row["title"], url=row["source_url"],
                                      source=row["source_name"],
                                      summary=row["summary"] or "—", skeleton=json.dumps(sk, indent=2)), encoding="utf-8")
        db.upsert_idea(con, idea_id, row["title"], source_url=row["source_url"], source_name=row["source_name"],
                       status="selected", script_path=str(sb_path))
        db.set_status(con, src_id, "used")
    return idea_id, sb_path, brief


# ---------------------------------------------------------------- CLI


def _cmd_discover(a, paths: Paths) -> int:
    _log()
    s = discover(paths)
    print(f"feeds {s['feeds']} (failed {len(s['failed'])}), entries {s['seen']}, new {s['new']}, duplicates {s['dupes']}")
    for f in s["failed"]:
        print("  failed:", f)
    return 0 if len(s["failed"]) < s["feeds"] else 1


def _cmd_rank(a, paths: Paths) -> int:
    _log()
    print(f"ranked {rank(paths)} items")
    return 0


def _cmd_shortlist(a, paths: Paths) -> int:
    print(shortlist(paths, a.size))
    return 0


def _cmd_daily(a, paths: Paths) -> int:
    _log()
    paths.ensure_dirs()
    s = discover(paths)
    rank(paths)
    out = shortlist(paths)
    print(f"new {s['new']}, failed feeds {len(s['failed'])} -> {out}")
    return 0 if len(s["failed"]) < s["feeds"] else 1


def _cmd_ideas(a, paths: Paths) -> int:
    waiting = ideas_waiting(paths)
    if not waiting:
        print(f"no idea notes waiting in {paths.ideas_inbox}")
    for p in waiting:
        print(f"{p.name:<40} {parse_note(p.read_text(encoding='utf-8'), p.stem)['title'][:70]}")
    return 0


def _cmd_new_idea(a, paths: Paths) -> int:
    idea_id, sb, brief = new_idea(paths, a.pick)
    print(f"created {idea_id}\n  storyboard: {sb}\n  Claude brief: {brief}\n"
          f"  record voiceover as: {paths.voiceovers / (idea_id + '.m4a')}")
    return 0


def _log():
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")


def add_commands(sub) -> None:
    sub.add_parser("discover", help="fetch RSS feeds into the idea database").set_defaults(fn=_cmd_discover)
    sub.add_parser("rank", help="score discovered items").set_defaults(fn=_cmd_rank)
    p = sub.add_parser("shortlist", help="write today's shortlist markdown")
    p.add_argument("--size", type=int)
    p.set_defaults(fn=_cmd_shortlist)
    sub.add_parser("daily", help="discover + rank + shortlist (for scheduling)").set_defaults(fn=_cmd_daily)
    p = sub.add_parser("new-idea", help="turn a shortlist pick into a storyboard + Claude brief")
    p.add_argument("pick", help="shortlist rank number (1..N), an RSS-… id, or your own idea .md "
                                "(a path, or a file name in inbox/ideas/)")
    p.set_defaults(fn=_cmd_new_idea)
    sub.add_parser("ideas", help="your own idea notes waiting in inbox/ideas/").set_defaults(fn=_cmd_ideas)
