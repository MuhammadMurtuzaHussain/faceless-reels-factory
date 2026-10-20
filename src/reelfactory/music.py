"""Original background music, synthesized locally (no samples, no licences needed).

A calm lo-fi bed: warm detuned pad chords, a soft plucked arpeggio, a round
bass note and very quiet percussion. Every idea gets its own variation
(progression, tempo, pattern) from a deterministic seed, so re-renders match.
"""
from __future__ import annotations

import hashlib

import numpy as np

SR = 48000

# warm, unresolved-feeling progressions (MIDI voicings, root first)
PROGRESSIONS = {
    "warm":    [[48, 55, 59, 64], [45, 52, 55, 60], [41, 48, 52, 57], [43, 50, 53, 59]],   # Cmaj7 Am7 Fmaj7 G7sus-ish
    "float":   [[41, 48, 52, 57], [43, 50, 55, 59], [40, 47, 50, 55], [45, 52, 55, 60]],   # Fmaj7 G Em7 Am7
    "soft":    [[50, 57, 60, 65], [43, 50, 53, 59], [48, 55, 59, 64], [45, 52, 55, 60]],   # Dm7 G7 Cmaj7 Am7
    "dawn":    [[45, 52, 55, 60], [41, 48, 52, 57], [48, 55, 59, 64], [43, 50, 55, 62]],   # Am7 Fmaj7 Cmaj7 G
}
ARP_PATTERNS = [[0, 1, 2, 3, 2, 1, 2, 3], [0, 2, 1, 3, 2, 3, 1, 2], [3, 2, 1, 2, 0, 2, 1, 3]]


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def seed_for(key: str) -> int:
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16)


def _place(buf: np.ndarray, start: float, sig: np.ndarray) -> None:
    i = int(start * SR)
    if i >= len(buf):
        return
    j = min(i + len(sig), len(buf))
    buf[i:j] += sig[: j - i]


def _pad_note(f: float, dur: float, rel: float = 0.9) -> np.ndarray:
    n = int((dur + rel) * SR)
    t = np.arange(n) / SR
    voice = np.zeros(n)
    for cents in (-6, 6):                         # two slightly detuned voices = gentle chorus
        ff = f * 2 ** (cents / 1200)
        voice += np.sin(2 * np.pi * ff * t) + 0.25 * np.sin(4 * np.pi * ff * t) + 0.08 * np.sin(6 * np.pi * ff * t)
    env = np.minimum(1, t / 0.7)                  # slow swell in
    env *= np.where(t > dur, np.exp(-(t - dur) / (rel / 3)), 1.0)
    return voice * env * (1 + 0.08 * np.sin(2 * np.pi * 0.23 * t))


def _pluck(f: float, vel: float) -> np.ndarray:
    n = int(0.9 * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * f * t) * np.exp(-t * 5.5) + 0.3 * np.sin(4 * np.pi * f * t) * np.exp(-t * 9)
    s[: int(0.004 * SR)] *= np.linspace(0, 1, int(0.004 * SR))
    return s * vel


def _bass(f: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * f * t) + 0.15 * np.sin(4 * np.pi * f * t)
    env = np.minimum(1, t / 0.02) * np.exp(-t * 1.6)
    return s * env


def _kick() -> np.ndarray:
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    f = 48 + 60 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 12)


def _shaker(rng: np.random.Generator) -> np.ndarray:
    n = int(0.06 * SR)
    noise = rng.standard_normal(n)
    hp = np.diff(noise, prepend=0)                # crude high-pass = soft "tss"
    return hp * np.exp(-np.arange(n) / SR * 70) * 0.5


def generate_bed(duration: float, key: str = "demo", mood: str | None = None, bpm: float | None = None,
                 drums: bool = True) -> tuple[np.ndarray, dict]:
    """Return (mono float signal at 48 kHz, info) of exactly ``duration`` seconds."""
    rng = np.random.default_rng(seed_for(key))
    mood = mood or list(PROGRESSIONS)[int(rng.integers(len(PROGRESSIONS)))]
    bpm = bpm or float(rng.choice([78, 82, 86, 90]))
    prog = PROGRESSIONS[mood]
    pattern = ARP_PATTERNS[int(rng.integers(len(ARP_PATTERNS)))]
    beat = 60 / bpm
    bar = 4 * beat
    n = int((duration + 2) * SR)
    pad, arp, bass, perc = (np.zeros(n) for _ in range(4))

    bars = int(np.ceil(duration / bar)) + 1
    for b in range(bars):
        chord = prog[b % len(prog)]
        t0 = b * bar
        for m in chord:
            _place(pad, t0, _pad_note(hz(m), bar))
        _place(bass, t0, _bass(hz(chord[0] - 12), bar))
        for k, idx in enumerate(pattern):         # eighth-note arpeggio, with a few rests to breathe
            if rng.random() < 0.18:
                continue
            _place(arp, t0 + k * beat / 2, _pluck(hz(chord[idx] + 12), rng.uniform(0.45, 0.8)))
        if drums:
            for q in range(4):
                if q in (0, 2):
                    _place(perc, t0 + q * beat, _kick() * 0.9)
                _place(perc, t0 + q * beat + beat / 2, _shaker(rng) * rng.uniform(0.6, 1.0))

    mix = 0.22 * pad / 8 + 0.28 * arp + 0.35 * bass + 0.25 * perc
    mix = mix[: int(duration * SR)]
    # fades + level: RMS to -20 dBFS, soft-clipped
    fade_in, fade_out = int(1.2 * SR), int(1.8 * SR)
    mix[:fade_in] *= np.linspace(0, 1, fade_in)
    mix[-fade_out:] *= np.linspace(1, 0, fade_out) ** 2
    rms = np.sqrt(np.mean(mix ** 2)) or 1.0
    mix = np.tanh(mix * (10 ** (-20 / 20) / rms) * 1.2) / 1.2
    return mix, {"generator": "reelfactory.music", "mood": mood, "bpm": bpm, "seed_key": key, "drums": drums}
