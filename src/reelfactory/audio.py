"""Original synthesized sound effects and the final FFmpeg audio mix."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 48000


def _env(n: int, attack: float, decay_pow: float = 3.0) -> np.ndarray:
    a = max(int(n * attack), 1)
    env = np.ones(n)
    env[:a] = np.linspace(0, 1, a)
    env[a:] = np.linspace(1, 0, n - a) ** decay_pow
    return env


def _lowpass(x: np.ndarray, cutoff: np.ndarray) -> np.ndarray:
    """One-pole low-pass with a per-sample cutoff (Hz)."""
    alpha = 1 - np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += alpha[i] * (x[i] - acc)
        y[i] = acc
    return y


def whoosh(rng: np.random.Generator) -> np.ndarray:
    n = int(0.42 * SR)
    t = np.linspace(0, 1, n)
    noise = rng.standard_normal(n)
    sweep = 300 + 5200 * np.sin(np.pi * t) ** 2
    lp = _lowpass(noise, sweep)
    hp = lp - _lowpass(lp, np.full(n, 180.0))
    return hp * np.sin(np.pi * t) ** 1.5 * 1.6


def tick(rng: np.random.Generator) -> np.ndarray:
    """Soft wooden tick."""
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * 1150 * t) * 0.55 + np.sin(2 * np.pi * 1720 * t) * 0.2
    return s * _env(n, 0.03, 5) * 0.55


def pop(rng: np.random.Generator) -> np.ndarray:
    """Gentle bubble pop for a card landing."""
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    f = 420 * np.exp(-t * 14) + 260
    s = np.sin(2 * np.pi * np.cumsum(f) / SR)
    return s * _env(n, 0.04, 3) * 0.5


def impact(rng: np.random.Generator) -> np.ndarray:
    n = int(0.7 * SR)
    t = np.arange(n) / SR
    f = 120 * np.exp(-t * 6) + 42
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 5)
    click = _lowpass(rng.standard_normal(n), np.full(n, 2500.0)) * np.exp(-t * 40) * 0.7
    return np.tanh((body + click) * 1.4) * 0.85


def blip(rng: np.random.Generator) -> np.ndarray:
    """Short friendly two-note blip (speech bubbles, emotes)."""
    n = int(0.16 * SR)
    t = np.arange(n) / SR
    f = np.where(t < 0.07, 880.0, 1320.0)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.6 + np.sin(4 * np.pi * np.cumsum(f) / SR) * 0.12
    return s * _env(n, 0.05, 2.5) * 0.4


def alert(rng: np.random.Generator) -> np.ndarray:
    """Soft digital warning: two quick descending beeps."""
    n = int(0.36 * SR)
    t = np.arange(n) / SR
    f = np.where(t < 0.16, 990.0, 740.0)
    gate = ((t % 0.18) < 0.12).astype(float)
    s = np.sign(np.sin(2 * np.pi * np.cumsum(f) / SR)) * 0.25 + np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.4
    return _lowpass(s * gate, np.full(n, 3200.0)) * _env(n, 0.02, 1.5) * 0.5


def typing(rng: np.random.Generator) -> np.ndarray:
    """A short burst of keyboard clicks."""
    n = int(0.7 * SR)
    out = np.zeros(n)
    t = 0.0
    while t < 0.62:
        i = int(t * SR)
        k = int(0.018 * SR)
        click = _lowpass(rng.standard_normal(k), np.full(k, 4000.0)) * np.exp(-np.arange(k) / (0.004 * SR))
        out[i:i + k] += click * (0.4 + 0.3 * rng.random())
        t += 0.05 + 0.05 * rng.random()
    return out * 0.6


SYNTHS = {"whoosh": whoosh, "tick": tick, "pop": pop, "impact": impact, "blip": blip, "alert": alert, "type": typing}


def write_wav(path: Path, data: np.ndarray, channels: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def ensure_sfx(sfx_dir: Path) -> dict[str, Path]:
    """Generate the SFX library once (deterministic seed) and return paths."""
    out = {}
    for seed, (name, fn) in enumerate(SYNTHS.items(), start=1):
        p = sfx_dir / f"{name}.wav"
        if not p.exists():
            write_wav(p, fn(np.random.default_rng(seed * 1009)))
        out[name] = p
    return out


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32767


def build_sfx_track(events: list[tuple[float, str]], duration: float, sfx: dict[str, Path], out: Path) -> Path:
    buf = np.zeros(int(duration * SR) + SR)
    cache = {k: read_wav(p) for k, p in sfx.items()}
    for t, kind in events:
        clip = cache[kind]
        i = int(t * SR)
        j = min(i + len(clip), len(buf))
        buf[i:j] += clip[: j - i]
    write_wav(out, buf[: int(duration * SR)])
    return out


def mix(voice: Path, sfx_track: Path, out: Path, duration: float, audio_cfg: dict, music: Path | None = None) -> Path:
    """Voice (loudness-normalised) + SFX + optional music ducked under the voice -> 48 kHz stereo WAV."""
    lufs = audio_cfg.get("voice_lufs", -14)
    mcfg = audio_cfg.get("music") or {}
    inputs = ["-i", str(voice), "-i", str(sfx_track)]
    fc = [f"[0:a]aformat=channel_layouts=mono,highpass=f=70,loudnorm=I={lufs}:TP=-1.5:LRA=11,"
          f"aresample={SR},apad=whole_dur={duration:.3f}[v]",
          f"[1:a]aresample={SR},volume={audio_cfg.get('sfx_gain', 0.3)}[s]"]
    if music:
        inputs = inputs + ["-stream_loop", "-1", "-i", str(music)]
        fc += ["[v]asplit=2[v1][vsc]",
               f"[2:a]aresample={SR},aformat=channel_layouts=mono,"
               + (f"loudnorm=I={mcfg['lufs']}:TP=-3:LRA=11,aresample={SR}," if mcfg.get("lufs") else "")
               + f"volume={mcfg.get('gain', 0.5)},"
               f"afade=t=out:st={max(0.0, duration - 1.6):.3f}:d=1.5[m]",
               f"[m][vsc]sidechaincompress=threshold={mcfg.get('duck_threshold', 0.03)}:"
               f"ratio={mcfg.get('duck_ratio', 8)}:attack=20:release=400[md]",
               "[v1][s][md]amix=inputs=3:normalize=0:duration=first[mx]"]
    else:
        fc += ["[v][s]amix=inputs=2:normalize=0:duration=first[mx]"]
    fc += ["[mx]alimiter=limit=0.89:level=false,aformat=channel_layouts=stereo[out]"]
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
           "-map", "[out]", "-t", f"{duration:.3f}", "-ar", str(SR), "-c:a", "pcm_s16le", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out


# ---------------------------------------------------------------- voice prep


def decode_mono(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64)


def find_pauses(x: np.ndarray, min_pause: float, hop_s: float = 0.01) -> tuple[list[tuple[float, float]], float]:
    """Silent stretches >= min_pause, using a threshold adapted to the recording's noise floor."""
    hop = int(hop_s * SR)
    n = len(x) // hop
    if n == 0:
        return [], -99.0
    db = 20 * np.log10(np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-9)
    win = 5   # 50 ms max-filter so quiet consonants don't split words
    smooth = np.array([db[max(0, i - win):i + win + 1].max() for i in range(n)])
    thr = float(min(np.percentile(db, 10) + 9, np.percentile(db, 90) - 18))
    silent = smooth < thr
    pauses, i = [], 0
    while i < n:
        if silent[i]:
            j = i
            while j < n and silent[j]:
                j += 1
            if (j - i) * hop_s >= min_pause or i == 0 or j == n:
                pauses.append((i * hop_s, j * hop_s))
            i = j
        else:
            i += 1
    return pauses, thr


def tighten_voice(src: Path, out: Path, cfg: dict) -> dict:
    """Trim dead air at the ends and shorten long pauses (jump-cut style).

    cfg keys: lead (s kept before first word), tail (s kept after last word),
    max_pause (s a pause is shortened to), min_pause (pauses shorter than this are untouched).
    """
    x = decode_mono(src)
    dur = len(x) / SR
    lead, tail = cfg.get("lead", 0.08), cfg.get("tail", 0.35)
    max_pause, min_pause = cfg.get("max_pause", 0.3), cfg.get("min_pause", 0.42)
    pauses, thr = find_pauses(x, min_pause)
    keep: list[tuple[int, int]] = []
    cursor = 0.0
    cuts = []
    for a, b in pauses:
        if a <= 0.0:                                   # leading silence
            cursor = max(0.0, b - lead)
            cuts.append((0.0, round(cursor, 3)))
            continue
        if b >= dur - 0.011:                           # trailing silence
            end = min(dur, a + tail)
            keep.append((int(cursor * SR), int(end * SR)))
            cuts.append((round(end, 3), round(dur, 3)))
            cursor = dur
            break
        half = max_pause / 2
        keep.append((int(cursor * SR), int((a + half) * SR)))
        cuts.append((round(a + half, 3), round(b - half, 3)))
        cursor = b - half
    if cursor < dur:
        keep.append((int(cursor * SR), len(x)))
    fade = int(0.012 * SR)
    pieces = []
    for s, e in keep:
        seg = x[s:e].copy()
        if len(seg) > 2 * fade:
            seg[:fade] *= np.linspace(0, 1, fade)
            seg[-fade:] *= np.linspace(1, 0, fade)
        pieces.append(seg)
    y = np.concatenate(pieces) if pieces else x
    write_wav(out, y)
    return {"original_duration": round(dur, 3), "tightened_duration": round(len(y) / SR, 3),
            "threshold_db": round(thr, 1), "removed": [c for c in cuts if c[1] - c[0] > 0.001]}


# ---------------------------------------------------------------- voice clarity

_CLEAN = "highpass=f=90:poles=2,afftdn=nr=14:nf=-48:tn=1"
ENHANCE_PRESETS = {
    # cut boom/mud, remove hiss *before* lifting presence, tame "s", even out level
    "light": _CLEAN + ",equalizer=f=150:t=q:w=1:g=-3,equalizer=f=3000:t=o:w=1.5:g=4,highshelf=f=8000:g=2,"
                      "acompressor=threshold=-22dB:ratio=2.5:attack=8:release=120:makeup=2",
    "balanced": _CLEAN + ",equalizer=f=160:t=q:w=1:g=-4,equalizer=f=350:t=q:w=1.2:g=-3,"
                         "equalizer=f=3000:t=o:w=1.5:g=6.5,equalizer=f=5500:t=o:w=1:g=2,highshelf=f=9000:g=1.5,"
                         "deesser=i=0.45,acompressor=threshold=-24dB:ratio=3:attack=8:release=120:makeup=3",
    "strong": _CLEAN + ",equalizer=f=150:t=q:w=1:g=-6,equalizer=f=350:t=q:w=1.2:g=-4,"
                       "equalizer=f=2800:t=o:w=1.5:g=9,equalizer=f=5500:t=o:w=1:g=4,highshelf=f=9000:g=3,"
                       "deesser=i=0.5,acompressor=threshold=-24dB:ratio=3.5:attack=6:release=120:makeup=4",
}


def enhance_voice(src: Path, out: Path, cfg: dict) -> dict:
    """Make a muffled/boomy recording clearer with a local FFmpeg chain (no AI services)."""
    chain = cfg.get("filters") or ENHANCE_PRESETS[cfg.get("preset", "balanced")]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", str(SR), "-af", chain,
                    "-c:a", "pcm_s16le", str(out)], check=True, capture_output=True, text=True)
    return {"preset": "custom" if cfg.get("filters") else cfg.get("preset", "balanced"),
            "before": tone_balance(src), "after": tone_balance(out)}


def tone_balance(path: Path) -> dict:
    """Speech energy per band (dB relative to total) plus high-band speech-to-noise ratio."""
    x = decode_mono(path)
    hop = 1024
    n = len(x) // hop
    fr = x[: n * hop].reshape(n, hop)
    rms = 20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-9)
    win = np.hanning(hop)
    sp = np.mean(np.abs(np.fft.rfft(fr[rms > np.percentile(rms, 70)] * win, axis=1)) ** 2, axis=0)
    nz = np.mean(np.abs(np.fft.rfft(fr[rms < np.percentile(rms, 10)] * win, axis=1)) ** 2, axis=0)
    f = np.fft.rfftfreq(hop, 1 / SR)
    tot = sp[(f > 50) & (f < 20000)].sum()

    def band(a, b):
        return round(float(10 * np.log10(sp[(f >= a) & (f < b)].sum() / tot)), 1)

    hi = (f >= 2000) & (f < 8000)
    return {"boom_50_150": band(50, 150), "clarity_2k_4k": band(2000, 4000), "sibilance_4k_8k": band(4000, 8000),
            "hi_snr_db": round(float(10 * np.log10(sp[hi].sum() / max(nz[hi].sum(), 1e-12))), 1)}
