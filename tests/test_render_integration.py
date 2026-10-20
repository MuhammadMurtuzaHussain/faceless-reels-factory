"""End-to-end: storyboard + synthetic voice -> validated MP4 (in an isolated root)."""
import json

import pytest

from conftest import have
from reelfactory import db
from reelfactory.pipeline import JobError, render_idea

pytestmark = pytest.mark.skipif(not have("ffmpeg", "ffprobe", "rsvg-convert"), reason="needs ffmpeg + rsvg-convert")

STORYBOARD = {
    "id": "TEST-001",
    "title": "Integration test",
    "script": "Your data is worth more. Apps track your location and habits.",
    "emphasis": ["location"],
    "scenes": [
        {"type": "card", "at": "Your data", "params": {"label": "Test", "headline": "Your data is worth *more*.",
                                                       "visual": {"type": "apps"}}},
        {"type": "card", "at": "Apps track", "params": {"label": "Collect", "headline": "Not just your *name*.",
         "visual": {"type": "rows", "rows": [{"icon": "pin", "label": "Location", "value": "Live", "at": "location"},
                                              {"icon": "repeat", "label": "Habits", "value": "Daily", "at": "habits"}]}}},
    ],
    "claims": [{"text": "test", "status": "illustrative"}],
    "caption": {"hook": "Test", "body": "Body", "cta": "Follow", "hashtags": ["#test"]},
}


def test_render_end_to_end(tmp_root, say_voice):
    tmp_root.storyboard("TEST-001").write_text(json.dumps(STORYBOARD))
    ok = render_idea(tmp_root, "TEST-001", voice=say_voice, workers=4)
    report = (tmp_root.drafts / "TEST-001.review.md").read_text()
    assert ok, report
    for p in (tmp_root.drafts / "TEST-001.mp4", tmp_root.covers / "TEST-001.jpg",
              tmp_root.manifests / "TEST-001.json", tmp_root.drafts / "TEST-001.caption.txt"):
        assert p.exists() and p.stat().st_size > 0, p
    manifest = json.loads((tmp_root.manifests / "TEST-001.json").read_text())
    assert manifest["validation"] == "PASS"
    assert not (tmp_root.work / "TEST-001" / "frames").exists()     # frames cleaned up
    with db.connect(tmp_root.db) as con:
        row = db.get(con, "TEST-001")
        assert row["status"] == "rendered" and row["attempts"] == 1


def test_missing_voiceover_is_a_clear_error(tmp_root):
    tmp_root.storyboard("TEST-001").write_text(json.dumps(STORYBOARD))
    with pytest.raises(JobError, match="no voiceover found"):
        render_idea(tmp_root, "TEST-001")


def test_tighten_voice_trims_dead_air(tmp_path, say_voice):
    import subprocess
    from reelfactory import audio
    from reelfactory.timing import probe_duration
    padded = tmp_path / "padded.wav"
    # 1.5 s silence + voice + 1.2 s silence
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "1.5", "-i", "anullsrc=r=48000:cl=mono",
                    "-i", str(say_voice), "-f", "lavfi", "-t", "1.2", "-i", "anullsrc=r=48000:cl=mono",
                    "-filter_complex", "[1:a]aresample=48000,aformat=channel_layouts=mono[v];[0:a][v][2:a]concat=n=3:v=0:a=1",
                    str(padded)], check=True)
    out = tmp_path / "tight.wav"
    info = audio.tighten_voice(padded, out, {"lead": 0.08, "tail": 0.35, "max_pause": 0.3, "min_pause": 0.42})
    assert info["removed"][0][0] == 0.0 and info["removed"][0][1] > 1.2      # leading silence removed
    assert info["tightened_duration"] < info["original_duration"] - 2.0
    assert abs(probe_duration(out) - info["tightened_duration"]) < 0.05


@pytest.mark.parametrize("preset", ["light", "balanced", "strong"])
def test_enhance_voice_presets(tmp_path, say_voice, preset):
    from reelfactory import audio
    from reelfactory.timing import probe_duration
    out = tmp_path / f"{preset}.wav"
    info = audio.enhance_voice(say_voice, out, {"preset": preset})
    assert out.exists() and abs(probe_duration(out) - probe_duration(say_voice)) < 0.1
    assert set(info["after"]) == {"boom_50_150", "clarity_2k_4k", "sibilance_4k_8k", "hi_snr_db"}


def test_generated_music_bed_is_deterministic_and_sane():
    import numpy as np
    from reelfactory import music
    a, info = music.generate_bed(6.0, key="AI-20261019-001")
    b, _ = music.generate_bed(6.0, key="AI-20261019-001")
    c, info_c = music.generate_bed(6.0, key="AI-20261020-001")
    assert len(a) == int(6.0 * music.SR) and np.array_equal(a, b)          # same idea -> same music
    assert not np.array_equal(a, c)                                        # different idea -> new variation
    assert np.abs(a).max() < 1.0 and np.sqrt(np.mean(a ** 2)) > 0.03       # not clipped, not silent
    assert info["mood"] in music.PROGRESSIONS and 70 <= info["bpm"] <= 100
