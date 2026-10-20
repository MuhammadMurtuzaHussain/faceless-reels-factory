"""Closing call to action: a 'follow' end card, plus one spoken line when ElevenLabs voices the Reel.

Defaults live in style.json ``cta``; a storyboard can override any field with its own ``cta`` object,
or switch it off with ``"cta": false``. Hand-recorded voiceovers don't contain the spoken line, so
for those the end card plays silently for ``hold_seconds`` after the voice ends.
"""
from __future__ import annotations


def config(sb: dict, style: dict) -> dict | None:
    base = style.get("cta") or {}
    own = sb.get("cta")
    if own is False or not base.get("enabled", False) and not own:
        return None
    return {**base, **(own if isinstance(own, dict) else {})}


def spoken_line(sb: dict, style: dict) -> str:
    cfg = config(sb, style)
    return (cfg or {}).get("spoken", "").strip()


def spoken_script(sb: dict, style: dict) -> str:
    """What ElevenLabs reads: the script, then the spoken CTA."""
    line = spoken_line(sb, style)
    return f"{sb['script'].strip()} {line}" if line else sb["script"].strip()


def scene(sb: dict, style: dict, spoken: bool) -> dict | None:
    """The end card as a storyboard scene; anchored to the spoken line, or placed after the voice."""
    cfg = config(sb, style)
    if cfg is None:
        return None
    line = cfg.get("spoken", "").split()
    anchor = " ".join(line[:3]) if spoken and line else None
    return {"type": "endcard", "at": anchor, "cta": True, "params": {
        "label": cfg.get("label", "Before you go"), "headline": cfg.get("headline", "Follow for *more*."),
        "size": cfg.get("size", 84), "_step": "",
        "follow_at": " ".join(line[len(line) // 2:][:2]) if spoken and line else None}}
