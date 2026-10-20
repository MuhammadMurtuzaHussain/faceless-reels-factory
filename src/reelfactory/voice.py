"""Voiceover from the storyboard script with your ElevenLabs voice clone (replaces recording by hand).

Needs ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in .env. Each call spends ElevenLabs credits
(about one per character of script), so a voiceover is only generated when none exists yet,
unless forced. A small sidecar ``<ID>.voice.json`` records which script text was spoken.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import check, cta, db, svg
from .paths import Paths, load_json, load_style, style_for

log = logging.getLogger(__name__)

API = "https://api.elevenlabs.io/v1"
SKELETON_MARK = "WRITE THE SPOKEN SCRIPT"
DEFAULT_MODEL = "eleven_v4"
DEFAULT_SETTINGS = {"stability": 0.5, "similarity_boost": 0.8, "style": 0.0, "use_speaker_boost": True}
SETTING_KEYS = ("stability", "similarity_boost", "style", "use_speaker_boost", "speed")


class VoiceError(Exception):
    """A failure with a message meant for the user."""


def load_env(paths: Paths) -> None:
    """Fill missing ELEVENLABS_* variables from .env (the CLI isn't started through stack-env.sh)."""
    f = paths.root / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and k.startswith("ELEVENLABS_") and not os.environ.get(k):
            os.environ[k] = v.strip().strip('"').strip("'")


def configured(paths: Paths) -> bool:
    load_env(paths)
    return bool(os.environ.get("ELEVENLABS_API_KEY") and os.environ.get("ELEVENLABS_VOICE_ID"))


def sidecar(paths: Paths, idea_id: str) -> Path:
    return paths.voiceovers / f"{idea_id}.voice.json"


def _meta(voice: Path) -> dict:
    """The sidecar of a voiceover this module generated, else {}."""
    try:
        meta = json.loads((voice.parent / f"{voice.stem}.voice.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return meta if meta.get("file") == voice.name else {}


def is_synthetic(voice: Path) -> bool:
    """True for a voiceover this module generated (it needs no clean-up EQ or denoising)."""
    return bool(_meta(voice))


def spoke_cta(voice: Path) -> bool:
    """True when the voiceover ends with the spoken call to action (hand recordings don't)."""
    return bool(_meta(voice).get("cta"))


def model(style: dict) -> str:
    return os.environ.get("ELEVENLABS_MODEL") or (style.get("voice") or {}).get("model") or DEFAULT_MODEL


def settings(style: dict) -> dict:
    """Voice settings from style.json ``voice`` (stability, similarity_boost, style, speed, ...)."""
    cfg = style.get("voice") or {}
    return {**DEFAULT_SETTINGS, **{k: cfg[k] for k in SETTING_KEYS if k in cfg}}


def script_sha(script: str) -> str:
    return hashlib.sha1(script.encode("utf-8")).hexdigest()


def post(endpoint: str, body: dict, accept: str = "audio/mpeg", timeout: int = 120) -> bytes:
    """POST to the ElevenLabs API and return the raw response (audio)."""
    req = urllib.request.Request(f"{API}/{endpoint}", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"],
                                          "Content-Type": "application/json", "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise VoiceError(f"ElevenLabs refused the request (HTTP {e.code}): {detail}") from e
    except urllib.error.URLError as e:
        raise VoiceError(f"could not reach ElevenLabs: {e.reason}") from e


def tts(text: str, style: dict) -> bytes:
    fmt = (style.get("voice") or {}).get("output_format", "mp3_44100_128")
    body = {"text": text, "model_id": model(style), "voice_settings": settings(style)}
    return post(f"text-to-speech/{os.environ['ELEVENLABS_VOICE_ID']}?output_format={fmt}", body)


def synthesize(paths: Paths, idea_id: str, force: bool = False) -> Path:
    """Speak the storyboard's script into inbox/voiceovers/<ID>.mp3; the watcher then renders it."""
    if not configured(paths):
        raise VoiceError("set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in .env first")
    sb_path = paths.storyboard(idea_id)
    if not sb_path.exists():
        raise VoiceError(f"storyboard not found: {sb_path.name}")
    sb = load_json(sb_path)
    script = sb.get("script", "").strip()
    if not script or script.startswith(SKELETON_MARK):
        raise VoiceError(f"{sb_path.name} is still the skeleton; fill in the script first")
    with db.connect(paths.db) as con:
        row = db.get(con, idea_id)
    if row and row["status"] in db.LOCKED and not force:
        raise VoiceError(f"{idea_id} is {row['status']}; its voiceover is protected")
    style = style_for(load_style(paths), sb)
    svg.set_font_dir(paths.fonts)
    bad = check.errors(check.check_storyboard(sb, style))
    if bad:                                        # don't pay for a voice the render would reject
        raise VoiceError("storyboard check failed: " + "; ".join(f"{c.name}: {c.detail}" for c in bad[:3])
                         + f" (run `reelfactory check {idea_id}`)")
    existing = paths.find_voiceover(idea_id)
    if existing and not force:
        raise VoiceError(f"{existing.name} already exists (use force to replace it)")

    spoken = cta.spoken_script(sb, style)            # the script, then the spoken call to action
    paths.voiceovers.mkdir(parents=True, exist_ok=True)
    log.info("ElevenLabs (%s): speaking %d characters for %s", model(style), len(spoken), idea_id)
    audio = tts(spoken, style)
    out = paths.voiceovers / f"{idea_id}.mp3"
    tmp = out.with_suffix(".part")                 # the watcher only picks up the finished file
    tmp.write_bytes(audio)
    if existing and existing != out:
        existing.unlink()
    tmp.replace(out)
    try:                                           # keep earlier takes' spend so the monthly budget stays right
        old = json.loads(sidecar(paths, idea_id).read_text(encoding="utf-8"))
        history = [*(old.get("history") or []), {k: old.get(k) for k in ("characters", "created_at")}]
    except (OSError, json.JSONDecodeError):
        history = []
    sidecar(paths, idea_id).write_text(json.dumps({
        "provider": "elevenlabs", "file": out.name, "voice_id": os.environ["ELEVENLABS_VOICE_ID"],
        "model": model(style), "settings": settings(style), "characters": len(spoken),
        "script_sha1": script_sha(script), "cta": spoken != script, "spoken": spoken, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **({"history": history} if history else {}),
    }, indent=2), encoding="utf-8")
    return out


def pending(paths: Paths) -> list[str]:
    """Picked ideas whose storyboard is filled in (and not a draft) but that have no voiceover yet."""
    out = []
    with db.connect(paths.db) as con:
        rows = con.execute("SELECT id FROM ideas WHERE status='selected' ORDER BY id").fetchall()
    for r in rows:
        sb = paths.storyboard(r["id"])
        if not sb.exists() or paths.find_voiceover(r["id"]):
            continue
        try:
            data = load_json(sb)
        except (json.JSONDecodeError, OSError):     # half-saved file: try again next minute
            continue
        script = data.get("script", "")
        if data.get("draft"):                       # still being written: wait for `reelfactory ready`
            continue
        if script.strip() and not script.startswith(SKELETON_MARK):
            out.append(r["id"])
    return out
