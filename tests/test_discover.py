import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from reelfactory import db, discover


def rss(items):
    body = "".join(f"<item><title>{t}</title><link>{u}</link><description>{d}</description>"
                   f"<pubDate>{format_datetime(p)}</pubDate></item>" for t, u, d, p in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>{body}</channel></rss>'


def test_canonical_url_and_similarity():
    assert discover.canonical_url("https://www.Example.com/a/?utm_source=x&id=2#frag") == "https://example.com/a?id=2"
    a = discover.title_tokens("OpenAI launches new voice cloning tool")
    b = discover.title_tokens("OpenAI launches voice cloning tool for developers")
    assert discover.jaccard(a, b) > 0.5


def test_daily_flow_offline(tmp_root):
    now = datetime.now(timezone.utc)
    feed = tmp_root.root / "feed.xml"
    feed.write_text(rss([
        ("Scammers clone voices with AI to steal money", "https://ex.com/a?utm_source=rss", "AI voice scam", now),
        ("Scammers clone voices with AI to steal money", "https://ex.com/a", "dupe link", now),
        ("New smartphone chip benchmark beats rivals", "https://ex.com/b", "chip", now - timedelta(hours=10)),
        ("Gardening tips for autumn", "https://ex.com/c", "plants", now),
        ("Very old AI story", "https://ex.com/d", "old", now - timedelta(days=30)),
    ]))
    cfg = json.loads(tmp_root.feeds_file.read_text())
    cfg["feeds"] = [{"name": "Local", "url": str(feed), "weight": 1.0}]
    tmp_root.feeds_file.write_text(json.dumps(cfg))

    s = discover.discover(tmp_root)
    assert s["new"] == 3 and s["dupes"] == 1 and not s["failed"]
    assert discover.discover(tmp_root)["new"] == 0          # second run: everything deduped
    discover.rank(tmp_root)
    with db.connect(tmp_root.db) as con:
        rows = con.execute("SELECT title, score, score_breakdown FROM ideas ORDER BY score DESC").fetchall()
    assert rows[0]["title"].startswith("Scammers")           # relevant + hooky beats gardening
    assert rows[-1]["title"].startswith("Gardening")
    assert set(json.loads(rows[0]["score_breakdown"])["factors"]) == set(cfg["ranking"]["weights"])

    md = discover.shortlist(tmp_root, size=2)
    assert "https://ex.com/a" in md.read_text()
    idea_id, sb, brief = discover.new_idea(tmp_root, "1")
    assert idea_id.startswith("AI-") and sb.exists() and brief.exists()
    assert json.loads(sb.read_text())["sources"][0]["url"].startswith("https://ex.com/a")
    with db.connect(tmp_root.db) as con:
        assert db.get(con, idea_id)["status"] == "selected"
