import json
from datetime import date, datetime, timezone

import pytest

from reelfactory import api, budget, db, review, voice
from reelfactory.pipeline import main
from test_api import call, login, running

from conftest import STORY_SCRIPT

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def sidecar(paths, idea_id, chars, created, history=None):
    meta = {"file": f"{idea_id}.mp3", "characters": chars, "created_at": created}
    if history:
        meta["history"] = history
    (paths.voiceovers / f"{idea_id}.voice.json").write_text(json.dumps(meta))


def set_limit(paths, limit):
    style = json.loads(paths.style_file.read_text())
    style["voice"]["monthly_characters"] = limit
    paths.style_file.write_text(json.dumps(style))


@pytest.fixture
def eleven(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "test-voice")
    calls = []
    monkeypatch.setattr(voice, "tts", lambda text, style: calls.append(text) or b"ID3fake mp3")
    return calls


def seed_story(paths, story_sb, idea_id="AI-20260101-001", status="selected", **over):
    paths.storyboard(idea_id).write_text(json.dumps(story_sb(idea_id, **over)))
    with db.connect(paths.db) as con:
        db.upsert_idea(con, idea_id, "Agents on the web", status=status)


# ---------------------------------------------------------------- budget meter

def test_budget_sums_this_calendar_month_including_replaced_takes(tmp_root):
    sidecar(tmp_root, "AI-20261020-001", 400, "2026-10-20T11:00:00+00:00",
            history=[{"characters": 450, "created_at": "2026-10-19T09:00:00+00:00"},
                     {"characters": 999, "created_at": "2026-09-30T09:00:00+00:00"}])   # last month
    sidecar(tmp_root, "AI-20261002-001", 300, "2026-10-02T08:00:00+00:00")
    (tmp_root.voiceovers / "broken.voice.json").write_text("{not json")
    assert budget.used_this_month(tmp_root, NOW) == 1150
    style = json.loads(tmp_root.style_file.read_text())
    b = budget.summary(tmp_root, style, NOW)
    assert b["limit"] is None and b["left"] is None and "set voice.monthly_characters" in budget.line(b)
    style["voice"]["monthly_characters"] = 10000
    b = budget.summary(tmp_root, style, NOW)
    assert (b["used"], b["left"]) == (1150, 8850)
    assert budget.line(b) == "ElevenLabs: 1,150 of 10,000 characters used in October 2026 (8,850 left)"
    style["voice"]["monthly_characters"] = 1000
    assert "150 OVER the limit" in budget.line(budget.summary(tmp_root, style, NOW))


def test_forced_revoice_keeps_the_old_take_in_history(tmp_root, eleven, story_sb):
    seed_story(tmp_root, story_sb)
    voice.synthesize(tmp_root, "AI-20260101-001")
    voice.synthesize(tmp_root, "AI-20260101-001", force=True)
    meta = json.loads(voice.sidecar(tmp_root, "AI-20260101-001").read_text())
    assert len(meta["history"]) == 1 and meta["history"][0]["characters"] == meta["characters"]
    assert budget.used_this_month(tmp_root) == 2 * len(eleven[0])
    assert voice.is_synthetic(tmp_root.voiceovers / "AI-20260101-001.mp3")


def test_check_and_status_show_budget(tmp_root, story_sb, capsys):
    seed_story(tmp_root, story_sb)
    set_limit(tmp_root, 10000)
    sidecar(tmp_root, "AI-20261001-001", 500, datetime.now(timezone.utc).isoformat())
    assert main(["--root", str(tmp_root.root), "check", "AI-20260101-001"]) == 0
    out = capsys.readouterr().out
    cost = budget.cost(tmp_root, "AI-20260101-001")
    assert "500 of 10,000 characters" in out and f"costs {cost:,} characters ({9500 - cost:,} left after)" in out
    main(["--root", str(tmp_root.root), "status"])
    assert "9,500 left" in capsys.readouterr().out
    reply = api.run_command(tmp_root, "/status")
    assert "9,500 left" in reply["reply"] and reply["budget"]["left"] == 9500


# ---------------------------------------------------------------- re-voice warning

def test_cli_revoice_asks_before_spending(tmp_root, eleven, story_sb, monkeypatch, capsys):
    seed_story(tmp_root, story_sb)
    set_limit(tmp_root, 10000)
    root = ["--root", str(tmp_root.root)]
    assert main([*root, "voice", "AI-20260101-001"]) == 0               # first take: no question asked
    assert len(eleven) == 1
    capsys.readouterr()
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert main([*root, "voice", "AI-20260101-001", "--force"]) == 1
    out = capsys.readouterr().out
    n = len(eleven[0])
    assert f"This spends {n:,} characters; {10000 - n:,} left this month ({10000 - 2 * n:,} after)" in out
    assert "not re-voiced" in out and len(eleven) == 1
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert main([*root, "voice", "AI-20260101-001", "--force"]) == 0 and len(eleven) == 2
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("--yes must not ask"))
    assert main([*root, "voice", "AI-20260101-001", "--force", "--yes"]) == 0 and len(eleven) == 3


def test_chat_revoice_quotes_cost_then_needs_yes(tmp_root, eleven, story_sb):
    seed_story(tmp_root, story_sb)
    set_limit(tmp_root, 10000)
    assert api.run_command(tmp_root, "/voice AI-20260101-001")["ok"] and len(eleven) == 1
    n = len(eleven[0])
    r = api.run_command(tmp_root, "/voice AI-20260101-001 force")
    assert r["ok"] and r["confirm"] and len(eleven) == 1
    assert f"spends {n:,} characters; {10000 - n:,} left" in r["reply"]
    assert "/voice AI-20260101-001 force yes" in r["reply"]
    r = api.run_command(tmp_root, "/voice AI-20260101-001 force yes")
    assert r["ok"] and len(eleven) == 2 and f"{10000 - 2 * n:,} left" in r["reply"]


def test_tight_budget_is_called_out(tmp_root, eleven, story_sb):
    seed_story(tmp_root, story_sb)
    voice.synthesize(tmp_root, "AI-20260101-001")
    set_limit(tmp_root, len(eleven[0]) + 10)
    assert "MORE than you have left" in api.run_command(tmp_root, "/voice AI-20260101-001 force")["reply"]


# ---------------------------------------------------------------- today view

def test_stages_follow_the_pipeline(tmp_root, story_sb):
    day = date.today().strftime("%Y%m%d")
    ids = [f"AI-{day}-{n:03d}" for n in (1, 2, 3, 4)]
    tmp_root.storyboard(ids[0]).write_text(json.dumps(story_sb(ids[0], draft=True)))
    tmp_root.storyboard(ids[1]).write_text(json.dumps(story_sb(ids[1])))
    tmp_root.storyboard(ids[2]).write_text(json.dumps(story_sb(ids[2])))
    (tmp_root.voiceovers / f"{ids[2]}.mp3").write_bytes(b"x")
    with db.connect(tmp_root.db) as con:
        for i, st in zip(ids, ("selected", "selected", "failed", "approved")):
            db.upsert_idea(con, i, i, status=st)
        db.upsert_idea(con, "AI-20200101-001", "old", status="published")
    rows = review.today(tmp_root)
    assert [(r["id"], r["stage"]) for r in rows] == list(zip(ids, ("draft", "ready", "voiced", "approved")))
    assert review.today(tmp_root, "20200101")[0]["stage"] == "published"
    status = api.run_command(tmp_root, "/status")["reply"]
    assert "4 of 3 reels" in status and "voiced (failed)" in status and "AI-20200101-001" in status


def test_dashboard_today_slots_and_meter(tmp_root, story_sb):
    day = date.today().strftime("%Y%m%d")
    rid = f"AI-{day}-001"
    seed_story(tmp_root, story_sb, rid, status="rendered")
    (tmp_root.voiceovers / f"{rid}.mp3").write_bytes(b"x")
    set_limit(tmp_root, 10000)
    sidecar(tmp_root, rid, 470, datetime.now(timezone.utc).isoformat())
    with running(tmp_root) as port:
        cookie, _ = login(port)
        _, _, raw = call(port, "GET", "/", headers={"Cookie": cookie})
    page = raw.decode()
    assert 'id="today"' in page and "1 of 3 reels" in page and page.count('class="slot open"') == 2
    assert '<li class="now">rendered</li>' in page and '<li class="done">voiced</li>' in page
    assert f'data-cmd="/approve {rid}"' in page                       # existing review actions in the slot
    assert "470 of 10,000 characters used" in page and "9,530 left" in page and "<meter" in page
    assert ' style="' not in page


def test_live_subscription_wins_and_refusal_falls_back(tmp_root, monkeypatch):
    import io
    import urllib.error
    import urllib.request
    monkeypatch.undo()                                   # use the real budget.live for this test
    budget._live_cache.clear()
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k-live")
    reply = json.dumps({"character_count": 1200, "character_limit": 30000,
                        "next_character_count_reset_unix": 1793000000}).encode()
    calls = []

    def ok(req, timeout):
        calls.append(req.full_url)
        return io.BytesIO(reply)
    monkeypatch.setattr(urllib.request, "urlopen", ok)
    b = budget.summary(tmp_root)
    assert (b["used"], b["limit"], b["left"], b["source"]) == (1200, 30000, 28800, "elevenlabs")
    assert "billing cycle" in budget.line(b) and calls == ["https://api.elevenlabs.io/v1/user/subscription"]
    budget.summary(tmp_root)
    assert len(calls) == 1                               # cached

    budget._live_cache.clear()
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k-tts-only")

    def refused(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "missing_permissions", {}, io.BytesIO(b""))
    monkeypatch.setattr(urllib.request, "urlopen", refused)
    sidecar(tmp_root, "AI-20261001-001", 500, datetime.now(timezone.utc).isoformat())
    b = budget.summary(tmp_root)
    assert (b["used"], b["limit"], b["source"]) == (500, None, "local")
