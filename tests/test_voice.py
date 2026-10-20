import json

import pytest

from reelfactory import api, db, review, voice
from reelfactory.paths import load_style


@pytest.fixture
def eleven(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "test-voice")
    calls = []
    monkeypatch.setattr(voice, "tts", lambda text, style: calls.append(text) or b"ID3fake mp3")
    return calls


from conftest import STORY_SCRIPT


@pytest.fixture
def seed(story_sb):
    def go(paths, script=STORY_SCRIPT, status="selected", **over):
        paths.storyboard("AI-20260101-001").write_text(json.dumps(story_sb(script=script, **over)))
        with db.connect(paths.db) as con:
            db.upsert_idea(con, "AI-20260101-001", "T", status=status)
    return go


def test_synthesize_writes_voice_and_sidecar(tmp_root, eleven, seed):
    seed(tmp_root)
    out = voice.synthesize(tmp_root, "AI-20260101-001")
    assert out.name == "AI-20260101-001.mp3" and eleven == [STORY_SCRIPT + " " + load_style(tmp_root)["cta"]["spoken"]]
    assert voice.is_synthetic(out) and voice.spoke_cta(out)
    items = review.inbox(tmp_root)                       # the sidecar is not mistaken for a voiceover
    assert [i["voiceover"] for i in items] == ["AI-20260101-001.mp3"] and items[0]["ready"]
    with pytest.raises(voice.VoiceError, match="already exists"):
        voice.synthesize(tmp_root, "AI-20260101-001")
    assert len(eleven) == 1


def test_synthesize_refuses_skeleton_and_locked(tmp_root, eleven, seed):
    seed(tmp_root, script="WRITE THE SPOKEN SCRIPT HERE")
    with pytest.raises(voice.VoiceError, match="skeleton"):
        voice.synthesize(tmp_root, "AI-20260101-001")
    seed(tmp_root, status="approved")
    with pytest.raises(voice.VoiceError, match="protected"):
        voice.synthesize(tmp_root, "AI-20260101-001")
    assert eleven == []


def test_watch_voices_then_renders(tmp_root, eleven, monkeypatch, seed):
    seed(tmp_root)
    rendered = []
    monkeypatch.setattr(api, "act_render", lambda paths, i, force=False: rendered.append(i) or api.resp("done"))
    r = api.act_watch(tmp_root)
    assert r["idle"] is False and rendered == ["AI-20260101-001"] and len(eleven) == 1


def test_watch_parks_failed_voice(tmp_root, eleven, monkeypatch, seed):
    seed(tmp_root)

    def boom(text, style):
        raise voice.VoiceError("HTTP 401")
    monkeypatch.setattr(voice, "tts", boom)
    assert api.act_watch(tmp_root)["ok"] is False
    assert api.act_watch(tmp_root)["idle"] is True       # not retried every minute
    with db.connect(tmp_root.db) as con:
        assert db.get(con, "AI-20260101-001")["status"] == "failed"


def test_cta_can_be_switched_off_per_storyboard(tmp_root, eleven, seed):
    seed(tmp_root)
    sb = json.loads(tmp_root.storyboard("AI-20260101-001").read_text())
    tmp_root.storyboard("AI-20260101-001").write_text(json.dumps({**sb, "cta": False}))
    out = voice.synthesize(tmp_root, "AI-20260101-001")
    assert eleven == [STORY_SCRIPT] and not voice.spoke_cta(out)


def test_watcher_skips_drafts_and_voice_refuses_broken_storyboards(tmp_root, eleven, seed, story_sb):
    seed(tmp_root, draft=True)
    assert voice.pending(tmp_root) == []                 # a draft waits for `reelfactory ready`
    seed(tmp_root)
    assert voice.pending(tmp_root) == ["AI-20260101-001"]
    sb = story_sb()
    sb["scenes"][1]["at"] = "a phrase nobody says"
    tmp_root.storyboard("AI-20260101-001").write_text(json.dumps(sb))
    with pytest.raises(voice.VoiceError, match="check failed"):
        voice.synthesize(tmp_root, "AI-20260101-001")
    assert eleven == []                                  # nothing billed
