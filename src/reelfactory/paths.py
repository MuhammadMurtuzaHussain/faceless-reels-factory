"""Project paths and config loading."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTS = (".wav", ".m4a", ".mp3", ".aiff", ".aif", ".flac", ".caf")


def default_root() -> Path:
    env = os.environ.get("REELFACTORY_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Paths:
    root: Path

    @classmethod
    def default(cls) -> "Paths":
        return cls(default_root())

    @property
    def config(self) -> Path: return self.root / "config"
    @property
    def style_file(self) -> Path: return self.config / "style.json"
    @property
    def feeds_file(self) -> Path: return self.config / "feeds.json"
    @property
    def fontconfig(self) -> Path: return self.config / "fonts.conf"
    @property
    def fonts(self) -> Path: return self.root / "assets" / "fonts"
    @property
    def music(self) -> Path: return self.root / "assets" / "music"
    @property
    def generated(self) -> Path: return self.root / "assets" / "generated"
    @property
    def sfx(self) -> Path: return self.generated / "sfx"
    @property
    def scripts(self) -> Path: return self.root / "data" / "scripts"
    @property
    def db(self) -> Path: return self.root / "data" / "ideas.db"
    @property
    def voiceovers(self) -> Path: return self.root / "inbox" / "voiceovers"
    @property
    def ideas_inbox(self) -> Path: return self.root / "inbox" / "ideas"
    @property
    def drafts(self) -> Path: return self.root / "output" / "drafts"
    @property
    def covers(self) -> Path: return self.root / "output" / "covers"
    @property
    def manifests(self) -> Path: return self.root / "output" / "manifests"
    @property
    def work(self) -> Path: return self.root / "output" / ".work"
    @property
    def logs(self) -> Path: return self.root / "logs"
    @property
    def whisper_model(self) -> Path: return self.root / "models" / "ggml-base.en.bin"

    def storyboard(self, idea_id: str) -> Path:
        return self.scripts / f"{idea_id}.json"

    def find_voiceover(self, idea_id: str) -> Path | None:
        for ext in AUDIO_EXTS:
            p = self.voiceovers / f"{idea_id}{ext}"
            if p.exists():
                return p
        return None

    def ensure_dirs(self) -> None:
        for d in (self.scripts, self.voiceovers, self.ideas_inbox, self.drafts, self.covers,
                  self.manifests, self.work, self.logs, self.sfx, self.music):
            d.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_style(paths: Paths) -> dict:
    style = load_json(paths.style_file)
    prof = style.get("profile") or {}
    if prof.get("avatar"):                     # project-relative in style.json, absolute for the renderer
        prof["avatar"] = str((paths.root / prof["avatar"]).resolve())
    return style


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def style_for(style: dict, sb: dict) -> dict:
    """The base style with the storyboard's theme (``themes`` in style.json) merged over it.

    A storyboard picks one with ``"theme"``; story storyboards default to the ``story`` theme."""
    name = sb.get("theme")
    if name is None and any(s.get("type") == "story" for s in sb.get("scenes", [])):
        name = "story"
    theme = (style.get("themes") or {}).get(name) if name else None
    return _merge(style, theme) if theme else style
