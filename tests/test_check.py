import json

from conftest import STORY_SCRIPT

from reelfactory import check, db, discover, pipeline
from reelfactory.paths import load_json


def names(checks, failing=True):
    return {c.name for c in checks if (not c.ok) == failing}


def test_valid_storyboard_has_no_errors(story_sb, style):
    checks = check.check_storyboard(story_sb(), style)
    assert check.errors(checks) == [], [c.line() for c in checks]


def test_estimate_spreads_words_in_order():
    words, dur = check.estimate_words(STORY_SCRIPT)
    assert 15 < dur < 30 and words[0].start == 0
    assert all(a.end <= b.start + 1e-6 for a, b in zip(words, words[1:])) and words[-1].end <= dur + 0.01


def test_catches_skeleton_bad_cues_and_unknown_vocab(story_sb, style):
    assert names(check.check_storyboard(story_sb(script="WRITE THE SPOKEN SCRIPT HERE"), style)) == {"script"}
    sb = story_sb()
    sb["scenes"][2]["at"] = "never said"
    sb["scenes"][0]["params"]["elements"][0]["do"][0].update(pose="moonwalk", mood="bored")
    sb["scenes"][1]["params"]["elements"][0]["kind"] = "spaceship"
    sb["scenes"][1]["params"]["elements"][1]["at"] = "cue phrase"
    bad = names(check.check_storyboard(sb, style))
    assert {"scene cues", "element cues", "story vocabulary", "placeholders"} <= bad
    msg = " ".join(c.detail for c in check.check_storyboard(sb, style))
    assert "moonwalk" in msg and "bored" in msg and "spaceship" in msg


def test_cue_in_a_later_scene_and_layout_only_warn(story_sb, style):
    sb = story_sb()
    sb["scenes"][0]["params"]["elements"][0]["do"][0]["at"] = "special lanes"   # belongs to scene 2
    sb["scenes"][1]["params"]["elements"][1]["y"] = 1600
    checks = check.check_storyboard(sb, style)
    assert check.errors(checks) == [] and {"cue timing", "layout"} <= names(checks)


def test_ready_clears_draft_only_when_checks_pass(tmp_root, story_sb, capsys):
    path = tmp_root.storyboard("AI-20260101-001")
    sb = story_sb(draft=True)
    sb["scenes"][1]["at"] = "never said"
    path.write_text(json.dumps(sb))
    args = type("A", (), {"id": "AI-20260101-001"})
    assert pipeline.cmd_ready(args, tmp_root) == 1 and load_json(path)["draft"] is True
    path.write_text(json.dumps(story_sb(draft=True)))
    assert pipeline.cmd_ready(args, tmp_root) == 0 and "draft" not in load_json(path)
    with db.connect(tmp_root.db) as con:
        assert db.get(con, "AI-20260101-001")["status"] == "selected"


def test_idea_note_becomes_storyboard_and_brief(tmp_root):
    note = tmp_root.ideas_inbox / "agent-passports.md"
    note.write_text("# Why AI agents need passports\n\nSee https://example.com/agent-ids.\nCompare to a border.\n")
    assert [p.name for p in discover.ideas_waiting(tmp_root)] == ["agent-passports.md"]
    idea_id, sb_path, brief = discover.new_idea(tmp_root, "agent-passports.md")
    sb = load_json(sb_path)
    assert sb["title"] == "Why AI agents need passports"
    assert sb["sources"] == [{"title": "Why AI agents need passports", "url": "https://example.com/agent-ids"}]
    assert "Compare to a border." in brief.read_text() and not note.exists()
    assert (tmp_root.ideas_inbox / "used" / f"{idea_id}-agent-passports.md").exists()
    with db.connect(tmp_root.db) as con:
        assert db.get(con, idea_id)["source_name"] == "my notes"


def test_dry_preview_needs_no_voiceover(tmp_root, story_sb):
    import shutil
    import pytest
    if not shutil.which("rsvg-convert"):
        pytest.skip("needs rsvg-convert")
    tmp_root.storyboard("AI-20260101-001").write_text(json.dumps(story_sb()))
    args = type("A", (), {"id": "AI-20260101-001", "dry": True, "voice": None, "t": None, "verbose": False})
    assert pipeline.cmd_preview(args, tmp_root) == 0
    assert (tmp_root.drafts / "AI-20260101-001.preview.jpg").stat().st_size > 10_000
