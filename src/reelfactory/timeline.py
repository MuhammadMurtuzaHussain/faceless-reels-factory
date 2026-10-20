"""Turn a storyboard + timed words into a concrete, serialisable timeline."""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field

from . import captions as cap
from .timing import Word, find_phrase

log = logging.getLogger(__name__)


@dataclass
class Scene:
    type: str
    start: float
    end: float
    params: dict
    word_index: int

    @property
    def dur(self) -> float:
        return self.end - self.start


@dataclass
class Timeline:
    duration: float
    voice_duration: float
    scenes: list[Scene]
    chunks: list[cap.Chunk]
    sfx: list[tuple[float, str]]
    warnings: list[str] = field(default_factory=list)

    def scene_at(self, t: float) -> int:
        for i, s in enumerate(self.scenes):
            if s.start <= t < s.end:
                return i
        return len(self.scenes) - 1


def _resolve_params(obj, words: list[Word], base_idx: int, scene_start: float, warnings: list[str]):
    """Replace phrase anchors (keys 'at' / '*_at') with local seconds."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if (k == "at" or k.endswith("_at")) and isinstance(v, str):
                try:
                    i = find_phrase(words, v, base_idx)
                    out[k] = round(words[i].start - scene_start, 3)
                except ValueError:
                    warnings.append(f"anchor {v!r} not found in script; using default timing")
                    out[k] = None
            else:
                out[k] = _resolve_params(v, words, base_idx, scene_start, warnings)
        return out
    if isinstance(obj, list):
        return [_resolve_params(v, words, base_idx, scene_start, warnings) for v in obj]
    return obj


def build(storyboard: dict, words: list[Word], voice_duration: float, style: dict) -> Timeline:
    warnings: list[str] = []
    total = voice_duration + style.get("tail_seconds", 0.8)
    raw = storyboard["scenes"]
    hold = (style.get("cta") or {}).get("hold_seconds", 2.6)
    starts, idxs = [], []
    prev_idx = 0
    for n, sc in enumerate(raw):
        if n == 0:
            starts.append(0.0)
            idxs.append(0)
            continue
        if sc.get("cta") and sc.get("at") is None:     # silent end card after a hand-recorded voice
            starts.append(max(voice_duration + 0.15, starts[-1] + 0.6))
            idxs.append(len(words) - 1)
            total = max(total, starts[-1] + hold)
            continue
        try:
            i = find_phrase(words, sc["at"], prev_idx)
        except ValueError:
            warnings.append(f"scene {n} anchor {sc.get('at')!r} not found; spacing evenly")
            i = min(len(words) - 1, prev_idx + max(1, (len(words) - prev_idx) // (len(raw) - n + 1)))
        prev_idx = i
        idxs.append(i)
        starts.append(max(words[i].start - 0.12, starts[-1] + 0.6))
        if sc.get("cta"):                              # give the spoken end card time to land
            total = max(total, starts[-1] + hold)
    beats = sum(1 for sc in raw if not sc.get("cta"))
    scenes = []
    for n, sc in enumerate(raw):
        end = starts[n + 1] if n + 1 < len(raw) else total
        params = _resolve_params(copy.deepcopy(sc.get("params", {})), words, idxs[n], starts[n], warnings)
        params.setdefault("_step", f"{n + 1:02d} / {beats:02d}")
        if sc["type"] == "story":
            params.setdefault("_cast", storyboard.get("cast") or {})
            params["_sid"] = n
        scenes.append(Scene(sc["type"], starts[n], end, params, idxs[n]))

    chunks = cap.build_chunks(words, style, storyboard.get("emphasis", []))
    tl = Timeline(total, voice_duration, scenes, chunks, [], warnings)
    tl.sfx = sfx_events(tl, style)
    for w in warnings:
        log.warning(w)
    return tl


def _anchor_times(obj, out: list[float]) -> None:
    """Collect every resolved cue time (keys 'at' / '*_at') inside scene params."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if (k == "at" or k.endswith("_at")) and isinstance(v, (int, float)):
                out.append(float(v))
            else:
                _anchor_times(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _anchor_times(v, out)


def sfx_events(tl: Timeline, style: dict) -> list[tuple[float, str]]:
    """Soft, sparse sound design: a pop when a new card lands, a tick on each cue."""
    from . import story
    ev: list[tuple[float, str]] = []
    for n, s in enumerate(tl.scenes):
        if s.type == "story":               # story scenes say which moments deserve a sound
            if n > 0:
                ev.append((s.start, "whoosh"))
            ev += [(s.start + t, k) for t, k in story.sfx(s.params) if t < s.dur + 0.2]
            continue
        ev.append((s.start + (0.1 if n == 0 else 0.15), "pop"))
        cues: list[float] = []
        _anchor_times(s.params, cues)
        ev += [(s.start + c, "tick") for c in cues if c > 0.3]
    out: list[tuple[float, str]] = []
    for t, k in sorted((max(0.0, t), k) for t, k in ev if t < tl.duration):
        if out and t - out[-1][0] < 0.12:       # two sounds on one beat just sound like a glitch
            if k == "impact":
                out[-1] = (out[-1][0], k)
            continue
        out.append((t, k))
    return out
