import os
import shutil
import subprocess
from pathlib import Path

import pytest

from reelfactory import svg
from reelfactory.paths import Paths, load_style

REAL_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def fonts():
    svg.set_font_dir(REAL_ROOT / "assets" / "fonts")


@pytest.fixture(scope="session")
def style():
    return load_style(Paths(REAL_ROOT))


@pytest.fixture
def tmp_root(tmp_path) -> Paths:
    """An isolated project root that shares the real config, fonts and model."""
    (tmp_path / "config").mkdir()
    for name in ("style.json", "fonts.conf", "feeds.json"):
        src = REAL_ROOT / "config" / name
        if src.exists():
            shutil.copy(src, tmp_path / "config" / name)
    (tmp_path / "assets").mkdir()
    os.symlink(REAL_ROOT / "assets" / "fonts", tmp_path / "assets" / "fonts")
    if (REAL_ROOT / "models").exists():
        os.symlink(REAL_ROOT / "models", tmp_path / "models")
    p = Paths(tmp_path)
    p.ensure_dirs()
    return p


def have(*tools: str) -> bool:
    return all(shutil.which(t) for t in tools)


@pytest.fixture
def say_voice(tmp_path):
    """Short synthetic voiceover (macOS `say`) used only as a test fixture."""
    if not have("say", "ffmpeg"):
        pytest.skip("needs macOS say + ffmpeg")
    out = tmp_path / "voice.aiff"
    subprocess.run(["say", "-o", str(out), "Your data is worth more. Apps track your location and habits."],
                   check=True)
    return out


STORY_SCRIPT = ("AI agents now browse the web for you. They read pages, compare prices and fill in forms while you "
                "wait. Shops are building special lanes just for them. That could make pages worse for people, with "
                "more checks to prove you are human. The rules written now decide who the web serves.")


@pytest.fixture
def story_sb():
    """A small storyboard that passes every pre-flight check."""
    def make(idea_id: str = "AI-20260101-001", **over) -> dict:
        sb = {
            "id": idea_id, "title": "Agents on the web", "theme": "story", "script": STORY_SCRIPT,
            "emphasis": ["agents", "human"],
            "cast": {"agent": {"kind": "bot", "color": "accent", "name": "Agent"},
                     "person": {"kind": "person", "color": "slate"}},
            "scenes": [
                {"type": "story", "at": "AI agents", "params": {"set": "stage", "elements": [
                    {"el": "actor", "who": "agent", "id": "a1", "x": 540, "enter": "drop",
                     "do": [{"at": "fill in forms", "pose": "type", "mood": "focused"}]}]}},
                {"type": "story", "at": "Shops are building", "params": {"set": "city", "transition": "whip",
                 "elements": [{"el": "prop", "kind": "building", "x": 700, "at": "special lanes"},
                              {"el": "label", "text": "agents only", "x": 540, "y": 1440, "at": "just for them"}]}},
                {"type": "story", "at": "That could make", "params": {"set": "room", "elements": [
                    {"el": "actor", "who": "person", "x": 300, "mood": "worried",
                     "do": [{"at": "prove you are human", "emote": "?", "say": "I'm human!"}]}]}},
                {"type": "story", "at": "The rules written", "params": {"set": "stage",
                 "title": {"text": "Who does the web *serve?*", "at": "who the web serves"}}},
            ],
            "thumbnail": {"label": "AI agents", "headline": "The web, *built for bots*", "set": "stage",
                          "actor": {"who": "agent", "mood": "grin", "pose": "cheer"}},
            "claims": [{"text": "Shops build agent lanes", "status": "verified", "note": "quote"}],
            "sources": [{"title": "Source", "url": "https://example.com/story"}],
        }
        sb.update(over)
        return sb
    return make


@pytest.fixture(autouse=True)
def no_live_budget(monkeypatch):
    """Tests never ask ElevenLabs for the subscription; the meter uses the local count."""
    from reelfactory import budget
    monkeypatch.setattr(budget, "live", lambda paths: None)
