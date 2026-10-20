"""Background music from Eleven Music: a small library generated once, then rotated per idea.

Generating per Reel would spend music minutes on every render (Starter includes about 40 a month),
so ``python -m reelfactory music-library`` makes a handful of instrumental beds up front and each
idea picks one by its ID. ``library.json`` records the prompt, model and date of every track.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import music, voice
from .paths import Paths

log = logging.getLogger(__name__)

MODEL = "music_v2_5"
BASE = ("Instrumental background music for a calm, smart tech explainer video, sits quietly under a voiceover. "
        "No vocals, no big drops, steady from start to finish, clean modern mix. ")
MOODS = [
    ("warm-keys", "Warm electric piano chords, soft brushed drums, round bass, mellow lo-fi, 84 bpm."),
    ("curious-pluck", "Light plucked synth arpeggio, airy pad, gentle kick and shaker, curious and optimistic, 96 bpm."),
    ("focus-pulse", "Minimal pulsing synth, soft sidechained pad, subtle clicks, focused and modern, 100 bpm."),
    ("night-drive", "Dreamy analog synth pads, slow muted guitar, deep soft bass, late-night calm, 80 bpm."),
    ("bright-mallet", "Marimba and soft mallets, warm strings pad, light percussion, bright and friendly, 104 bpm."),
    ("ambient-glass", "Glassy ambient textures, slow evolving pad, very soft pulse, thoughtful, 72 bpm."),
]


def library_dir(paths: Paths) -> Path:
    return paths.music / "elevenlabs"


def tracks(paths: Paths) -> list[Path]:
    return sorted(library_dir(paths).glob("*.mp3"))


def pick(paths: Paths, idea_id: str) -> Path | None:
    """The same track for the same idea, spread evenly across the library."""
    lib = tracks(paths)
    return lib[music.seed_for(idea_id) % len(lib)] if lib else None


def info(paths: Paths, track: Path) -> dict:
    try:
        meta = json.loads((library_dir(paths) / "library.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        meta = {}
    return {"file": str(track), **meta.get(track.name, {}),
            "license": "Generated with Eleven Music on the user's ElevenLabs plan (see ElevenLabs Music terms)"}


def make_library(paths: Paths, count: int = 6, seconds: int = 45, force: bool = False) -> list[Path]:
    """Generate up to ``count`` instrumental tracks; existing ones are kept unless forced."""
    if not voice.configured(paths):
        raise voice.VoiceError("set ELEVENLABS_API_KEY in .env first")
    d = library_dir(paths)
    d.mkdir(parents=True, exist_ok=True)
    meta_file = d / "library.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    made = []
    for n, (name, mood) in enumerate(MOODS[:count], start=1):
        out = d / f"{n:02d}-{name}.mp3"
        if out.exists() and not force:
            continue
        prompt = BASE + mood
        log.info("Eleven Music: %s (%ds)", out.name, seconds)
        audio = voice.post("music?output_format=mp3_44100_128", {
            "prompt": prompt, "music_length_ms": seconds * 1000, "model_id": MODEL, "force_instrumental": True},
            timeout=300)
        tmp = out.with_suffix(".part")
        tmp.write_bytes(audio)
        tmp.replace(out)
        meta[out.name] = {"prompt": prompt, "model": MODEL, "seconds": seconds,
                          "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        made.append(out)
    return made
