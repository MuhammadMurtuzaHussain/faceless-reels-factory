"""ElevenLabs character budget: what the voiceovers spent this calendar month, against the plan's allowance.

Spending is read from the ``inbox/voiceovers/<ID>.voice.json`` sidecars (``characters`` and ``created_at``,
plus the ``history`` of earlier takes that a forced re-voice replaced). The allowance is
``voice.monthly_characters`` in style.json; ``null`` means "not set", so usage is shown without a limit.

When the API key has the ``user_read`` permission, ElevenLabs' own count for the billing cycle
(GET /v1/user/subscription, free) is used instead; without it the local count is used. The answer, or
the refusal, is cached for a few minutes so pages and /status don't call ElevenLabs each time.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime

from . import cta, voice
from .paths import Paths, load_json, load_style, style_for


def _local(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts).astimezone()
    except (TypeError, ValueError):
        return None


def takes(paths: Paths) -> list[dict]:
    """Every ElevenLabs take on record: [{"id", "characters", "created_at"}], replaced ones included."""
    out = []
    for f in sorted(paths.voiceovers.glob("*.voice.json")) if paths.voiceovers.exists() else []:
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        idea_id = f.name.removesuffix(".voice.json")
        for t in [*(meta.get("history") or []), meta]:
            if isinstance(t.get("characters"), int):
                out.append({"id": idea_id, "characters": t["characters"], "created_at": t.get("created_at")})
    return out


def used_this_month(paths: Paths, now: datetime | None = None) -> int:
    now = (now or datetime.now()).astimezone()
    total = 0
    for t in takes(paths):
        when = _local(t["created_at"])
        if when and (when.year, when.month) == (now.year, now.month):
            total += t["characters"]
    return total


def monthly_limit(style: dict) -> int | None:
    lim = (style.get("voice") or {}).get("monthly_characters")
    return lim if isinstance(lim, int) and lim > 0 else None


LIVE_TTL = 600                    # seconds a subscription answer (or refusal) is reused
_live_cache: dict = {}


def live(paths: Paths) -> dict | None:
    """{"used", "limit", "resets"} from ElevenLabs when the key may read the subscription, else None."""
    voice.load_env(paths)
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return None
    hit = _live_cache.get(key)
    if hit and time.monotonic() - hit[0] < LIVE_TTL:
        return hit[1]
    req = urllib.request.Request(f"{voice.API}/user/subscription", headers={"xi-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            sub = json.loads(r.read())
        out = {"used": int(sub["character_count"]), "limit": int(sub["character_limit"]),
               "resets": sub.get("next_character_count_reset_unix")}
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):   # no user_read, offline, odd reply
        out = None
    _live_cache[key] = (time.monotonic(), out)
    return out


def summary(paths: Paths, style: dict | None = None, now: datetime | None = None, use_live: bool = True) -> dict:
    """{"month", "used", "limit", "left", "source"}; ``limit``/``left`` are None when no allowance is known.

    ``source`` is "elevenlabs" (their billing-cycle count) or "local" (sidecars this calendar month)."""
    style = style if style is not None else load_style(paths)
    now = (now or datetime.now()).astimezone()
    sub = live(paths) if use_live else None
    if sub:
        resets = datetime.fromtimestamp(sub["resets"]).strftime("%-d %b") if sub.get("resets") else None
        return {"month": f"this billing cycle (resets {resets})" if resets else "this billing cycle",
                "used": sub["used"], "limit": sub["limit"], "left": sub["limit"] - sub["used"], "source": "elevenlabs"}
    used = used_this_month(paths, now)
    limit = monthly_limit(style)
    return {"month": now.strftime("%B %Y"), "used": used, "limit": limit,
            "left": None if limit is None else limit - used, "source": "local"}


def line(b: dict) -> str:
    """One plain-text line, e.g. 'ElevenLabs: 2,196 of 30,000 characters used in October 2026 (27,804 left)'."""
    if b["limit"] is None:
        return (f"ElevenLabs: {b['used']:,} characters used in {b['month']} "
                f"(set voice.monthly_characters in config/style.json to see what's left)")
    left = f"{b['left']:,} left" if b["left"] >= 0 else f"{-b['left']:,} OVER the limit"
    return f"ElevenLabs: {b['used']:,} of {b['limit']:,} characters used in {b['month']} ({left})"


def cost(paths: Paths, idea_id: str, style: dict | None = None) -> int:
    """Characters ElevenLabs would bill to voice this storyboard now (script plus spoken call to action)."""
    style = style if style is not None else load_style(paths)
    sb = load_json(paths.storyboard(idea_id))
    return len(cta.spoken_script(sb, style_for(style, sb)))


def spend_note(paths: Paths, idea_id: str, style: dict | None = None) -> str:
    """'This spends 472 characters; 27,804 left this month (27,332 after).' for re-voice warnings."""
    style = style if style is not None else load_style(paths)
    n = cost(paths, idea_id, style)
    b = summary(paths, style)
    if b["left"] is None:
        return f"This spends {n:,} characters ({b['used']:,} used this month; no monthly limit set)."
    after = b["left"] - n
    warn = " That is MORE than you have left." if after < 0 else ""
    return f"This spends {n:,} characters; {b['left']:,} left this month ({after:,} after).{warn}"
