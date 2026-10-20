"""Pre-flight checks for a storyboard, run before any ElevenLabs credits or render time are spent.

Everything here works from the text alone: word timing is estimated from the script (about the pace of
the voice clone), so cue phrases, caption layout and scene lengths can be checked before a voice exists.
"""
from __future__ import annotations

import re

from . import cast, cta, story
from . import timeline as tlmod
from .timing import Word, find_phrase, normalize, tokenize_script
from .validate import Check

SKELETON_MARK = "WRITE THE SPOKEN SCRIPT"
PLACEHOLDERS = ("cue phrase", "exact phrase", "first two words of the script", "Short line", "short tag",
                "2-3 word tag", "3-7 word cover line", "word1", "quote + URL")
CHARS_PER_SECOND = 14.0       # ElevenLabs v4 with this clone: 458 spoken characters took 32.6 s
ELEMENTS = ("actor", "prop", "swarm", "grid", "counter", "label", "stamp", "link", "crowd", "confetti", "text")
ENTERS = ("pop", "drop", "rise", "grow", "slam", "fade", "walk-left", "walk-right", "fly-left", "fly-right", "none")
TRANSITIONS = ("cut", "whip", "iris", "zoom", "fade")
EMOTES = ("!", "!!", "?", "sparkle", "heart", "zzz", "sweat", "idea", "check", "cross", "music")
CLAIM_STATUS = ("verified", "uncertain", "general")
WORDS_OK = (55, 75)
WORDS_HARD = (30, 110)


def estimate_words(script: str) -> tuple[list[Word], float]:
    """Spread the script over an estimated voice duration, with small pauses at punctuation."""
    toks = tokenize_script(script)
    weights = [len(normalize(t)) + 1 + (3 if t[-1] in ".!?:" else 1.5 if t[-1] in ",;" else 0) for t in toks]
    total = max(1.0, len(" ".join(toks)) / CHARS_PER_SECOND)
    unit = total / max(1, sum(weights))
    words, t = [], 0.0
    for tok, w in zip(toks, weights):
        speak = (len(normalize(tok)) + 1) * unit
        words.append(Word(tok, round(t, 3), round(t + speak, 3)))
        t += w * unit
    return words, total


def _strings(obj, path: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def _anchors(obj, path: str = ""):
    """Every phrase cue (keys 'at' / '*_at' holding text) with its path."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            if (k == "at" or k.endswith("_at")) and isinstance(v, str):
                yield p, v
            else:
                yield from _anchors(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _anchors(v, f"{path}[{i}]")


def _base_pose(p: str) -> str:
    return p.removesuffix("-left")


def _vocab(n: int, p: dict, cast_ids: set[str]) -> list[str]:
    """Unknown sets, elements, moods, poses, props and emotes in one story scene."""
    bad = []
    where = f"scene {n + 1}"
    if p.get("set", "stage") not in story.SETS:
        bad.append(f"{where}: unknown set {p.get('set')!r} (use {', '.join(sorted(story.SETS))})")
    if p.get("transition") and p["transition"] not in TRANSITIONS:
        bad.append(f"{where}: unknown transition {p['transition']!r}")
    for i, e in enumerate(p.get("elements", [])):
        kind = e.get("el", "actor" if "who" in e else "prop")
        tag = f"{where} element {i + 1} ({kind})"
        if kind not in ELEMENTS:
            bad.append(f"{tag}: unknown element type")
            continue
        if kind == "prop" and e.get("kind") not in cast.PROPS:
            bad.append(f"{tag}: unknown prop {e.get('kind')!r}")
        if kind in ("actor", "swarm", "crowd") and e.get("who") and e["who"] not in cast_ids:
            bad.append(f"{tag}: {e['who']!r} is not in cast")
        for key in ("enter", "exit"):
            if e.get(key) and e[key] not in ENTERS:
                bad.append(f"{tag}: unknown {key} {e[key]!r}")
        steps = [e] + [d for d in e.get("do", []) if isinstance(d, dict)]
        for d in steps:
            if d.get("mood") and d["mood"] not in cast.MOODS:
                bad.append(f"{tag}: unknown mood {d['mood']!r}")
            if d.get("pose") and _base_pose(d["pose"]) not in cast.POSES:
                bad.append(f"{tag}: unknown pose {d['pose']!r}")
            if d.get("emote") and d["emote"] not in EMOTES:
                bad.append(f"{tag}: unknown emote {d['emote']!r}")
    return bad


def _layout(n: int, p: dict) -> list[str]:
    out = []
    for i, e in enumerate(p.get("elements", [])):
        kind = e.get("el", "actor" if "who" in e else "prop")
        x, y = e.get("x"), e.get("y")
        tag = f"scene {n + 1} element {i + 1} ({kind})"
        if isinstance(x, (int, float)) and not 0 <= x <= 1080:
            out.append(f"{tag}: x {x} is off screen (0–1080)")
        if isinstance(y, (int, float)):
            if y < 480:
                out.append(f"{tag}: y {y} is under the captions (keep below 480)")
            if kind in ("label", "counter", "stamp") and y > 1450:
                out.append(f"{tag}: y {y} is under Instagram's UI (keep labels above 1450)")
        if kind == "actor":
            for d in e.get("do", []):
                if isinstance(d, dict) and isinstance(d.get("say"), str) and len(d["say"]) > 28:
                    out.append(f"{tag}: speech bubble {d['say']!r} is long (keep it under ~28 characters)")
    return out


def check_storyboard(sb: dict, style: dict) -> list[Check]:
    out: list[Check] = []
    script = (sb.get("script") or "").strip()
    if not script or script.startswith(SKELETON_MARK):
        return [Check("script", False, "the script is still the skeleton")]

    leftovers = sorted({path for path, s in _strings(sb) if any(ph in s for ph in PLACEHOLDERS)})
    out.append(Check("placeholders", not leftovers,
                     "none left" if not leftovers else f"skeleton text still in: {', '.join(leftovers[:6])}"))

    n_words = len(tokenize_script(script))
    lo, hi = WORDS_OK
    usable = WORDS_HARD[0] <= n_words <= WORDS_HARD[1]
    out.append(Check("script length", lo <= n_words <= hi, f"{n_words} words (aim for {lo}–{hi})",
                     severity="warn" if usable else "error"))
    last = re.split(r"(?<=[.!?])\s+", script)[-1].lower()
    out.append(Check("no spoken follow ask", "follow" not in last,
                     "fine" if "follow" not in last else "the last sentence says 'follow'; the CTA is added for you",
                     severity="warn"))

    scenes = sb.get("scenes") or []
    if not scenes:
        out.append(Check("scenes", False, "no scenes"))
        return out
    cast_ids = set((sb.get("cast") or {}).keys())
    words = tokenize_script(script)

    # scene cues: found in the script, in order
    starts, prev, bad_scene = [0], 0, []
    for n, sc in enumerate(scenes[1:], 1):
        try:
            i = find_phrase(words, sc.get("at", ""), prev)
            if i < prev:
                bad_scene.append(f"scene {n + 1} cue {sc.get('at')!r} comes before scene {n}")
            prev = max(prev, i)
        except ValueError:
            bad_scene.append(f"scene {n + 1} cue {sc.get('at')!r} is not in the script")
        starts.append(prev)
    out.append(Check("scene cues", not bad_scene, f"{len(scenes)} scenes, cues in order" if not bad_scene
                     else "; ".join(bad_scene[:4])))

    # element cues: found in the script, inside their own scene
    missing, outside = [], []
    for n, sc in enumerate(scenes):
        lo_i = starts[n]
        hi_i = starts[n + 1] if n + 1 < len(starts) else len(words)
        for path, phrase in _anchors(sc.get("params", {})):
            try:
                i = find_phrase(words, phrase, lo_i)
            except ValueError:
                missing.append(f"scene {n + 1} {path} {phrase!r}")
                continue
            if not lo_i <= i < hi_i:
                outside.append(f"scene {n + 1} {path} {phrase!r}")
    out.append(Check("element cues", not missing, "every cue is a phrase from the script" if not missing
                     else "not in the script: " + "; ".join(missing[:5])))
    if outside:
        out.append(Check("cue timing", False, "cue falls outside its scene (it won't be seen): "
                         + "; ".join(outside[:5]), severity="warn"))

    vocab, layout = [], []
    for n, sc in enumerate(scenes):
        if sc.get("type") == "story":
            vocab += _vocab(n, sc.get("params", {}), cast_ids)
            layout += _layout(n, sc.get("params", {}))
    out.append(Check("story vocabulary", not vocab, "sets, elements, moods, poses and props all exist" if not vocab
                     else "; ".join(vocab[:5])))
    if layout:
        out.append(Check("layout", False, "; ".join(layout[:5]), severity="warn"))

    thumb = sb.get("thumbnail") or {}
    head = thumb.get("headline", "")
    accents = head.count("*")
    thumb_ok = bool(head) and accents == 2 and 3 <= len(head.replace("*", "").split()) <= 8
    out.append(Check("thumbnail", thumb_ok, f"{head!r}" if thumb_ok else
                     f"needs a 3–7 word headline with one *accent* (got {head!r})", severity="warn"))

    srcs = [s for s in sb.get("sources") or [] if s.get("url")]
    out.append(Check("sources", bool(srcs), f"{len(srcs)} with a URL" if srcs else "no source URL"))
    claims = sb.get("claims") or []
    bad_status = [c.get("status") for c in claims if c.get("status") not in CLAIM_STATUS]
    out.append(Check("claims", bool(claims) and not bad_status,
                     f"{len(claims)} listed" if claims and not bad_status
                     else "no claims listed" if not claims else f"status must be one of {CLAIM_STATUS}: {bad_status}",
                     severity="warn"))
    unsure = [c["text"] for c in claims if c.get("status") == "uncertain"]
    if unsure:
        out.append(Check("uncertain claims", False, "verify before posting: " + "; ".join(unsure[:3]), severity="warn"))

    # caption layout and scene lengths, on estimated timing with the spoken CTA appended
    spoken = cta.spoken_script(sb, style)
    est, dur = estimate_words(spoken)
    end = cta.scene(sb, style, True)
    sb_tl = {**sb, "scenes": [*scenes, end]} if end else sb
    tl = tlmod.build(sb_tl, est, dur, style)
    from .validate import validate_timeline
    out += [c for c in validate_timeline(tl, style) if c.name != "timeline"]
    out.append(Check("estimate", True, f"~{dur:.0f}s of voice, {len(spoken)} ElevenLabs characters", severity="warn"))
    return out


def errors(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.ok and c.severity != "warn"]
