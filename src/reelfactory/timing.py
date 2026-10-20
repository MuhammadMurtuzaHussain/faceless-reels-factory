"""Word timing: whisper.cpp word timestamps aligned to the script, with a
silence-detection fallback when whisper is unavailable."""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Word:
    text: str          # display text, punctuation kept
    start: float
    end: float

    def to_dict(self) -> dict:
        return asdict(self)


def normalize(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower().replace("’", "'"))


def tokenize_script(script: str) -> list[str]:
    return [w for w in script.replace("“", '"').replace("”", '"').split() if normalize(w)]


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


# ---------------------------------------------------------------- whisper


def whisper_available(model: Path) -> bool:
    return shutil.which("whisper-cli") is not None and model.exists()


def transcribe_whisper(audio: Path, model: Path, threads: int = 8) -> list[Word]:
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "a16k.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(audio), "-ar", "16000", "-ac", "1", str(wav)],
                       check=True)
        out = Path(td) / "w"
        subprocess.run(["whisper-cli", "-m", str(model), "-f", str(wav), "-ml", "1", "-sow", "-oj",
                        "-of", str(out), "-np", "-t", str(threads), "-l", "en"],
                       check=True, capture_output=True)
        data = json.loads((out.with_suffix(".json")).read_text())
    words = []
    for seg in data.get("transcription", []):
        t = seg["text"].strip()
        if not normalize(t):
            continue
        words.append(Word(t, seg["offsets"]["from"] / 1000, seg["offsets"]["to"] / 1000))
    return words


# ---------------------------------------------------------------- fallback


def speech_segments(audio: Path, noise_db: float = -35, min_silence: float = 0.18) -> list[tuple[float, float]]:
    """Non-silent intervals via ffmpeg silencedetect."""
    dur = probe_duration(audio)
    res = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(audio), "-af",
                          f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
                         capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", res.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", res.stderr)]
    silences = list(zip(starts, ends + [dur] * (len(starts) - len(ends))))
    segs, cur = [], 0.0
    for s, e in silences:
        if s - cur > 0.05:
            segs.append((cur, s))
        cur = e
    if dur - cur > 0.05:
        segs.append((cur, dur))
    return segs or [(0.0, dur)]


def distribute(script_words: list[str], segments: list[tuple[float, float]]) -> list[Word]:
    """Spread words over speech segments weighted by character length."""
    weights = [len(normalize(w)) + 1.5 for w in script_words]
    total_w = sum(weights)
    total_t = sum(e - s for s, e in segments)
    words, acc = [], 0.0

    def to_time(pos: float) -> float:
        for s, e in segments:
            if pos <= e - s:
                return s + pos
            pos -= e - s
        return segments[-1][1]

    for w, wt in zip(script_words, weights):
        a = acc / total_w * total_t
        acc += wt
        b = acc / total_w * total_t
        words.append(Word(w, to_time(a), to_time(b - 1e-6)))
    return words


# ---------------------------------------------------------------- alignment


def align(script_words: list[str], heard: list[Word], duration: float) -> tuple[list[Word], float]:
    """Give each script word a time using matched transcript words; interpolate the rest.

    Returns (timed words, match ratio 0..1).
    """
    a = [normalize(w) for w in script_words]
    b = [normalize(w.text) for w in heard]
    sm = SequenceMatcher(a=a, b=b, autojunk=False)
    times: list[tuple[float, float] | None] = [None] * len(a)
    matched = 0
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            hw = heard[blk.b + k]
            times[blk.a + k] = (hw.start, hw.end)
            matched += 1
    # interpolate gaps between known anchors
    i = 0
    n = len(a)
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else (heard[0].start if heard else 0.0)
        right = times[j][0] if j < n else (heard[-1].end if heard else duration)
        right = max(right, left + 0.08 * (j - i))
        weights = [len(x) + 1.5 for x in a[i:j]]
        tot, acc = sum(weights), 0.0
        for k, wt in zip(range(i, j), weights):
            s = left + (right - left) * acc / tot
            acc += wt
            times[k] = (s, left + (right - left) * acc / tot)
        i = j
    words = [Word(w, *t) for w, t in zip(script_words, times)]
    fix_monotonic(words, duration)
    return words, matched / max(n, 1)


def fix_monotonic(words: list[Word], duration: float) -> None:
    prev = 0.0
    for w in words:
        w.start = max(w.start, prev)
        w.end = min(max(w.end, w.start + 0.05), duration)
        prev = w.start
    for a, b in zip(words, words[1:]):
        a.end = min(a.end, b.start) if b.start > a.start else a.end


def find_phrase(words: list[Word] | list[str], phrase: str, start: int = 0) -> int:
    toks = [normalize(x) for x in phrase.split()]
    seq = [normalize(w.text if isinstance(w, Word) else w) for w in words]
    for i in range(start, len(seq) - len(toks) + 1):
        if seq[i:i + len(toks)] == toks:
            return i
    for i in range(0, len(seq) - len(toks) + 1):
        if seq[i:i + len(toks)] == toks:
            return i
    raise ValueError(f"phrase not found in script: {phrase!r}")


def time_words(script: str, audio: Path, model: Path) -> tuple[list[Word], dict]:
    """Main entry: timed script words + info about how they were obtained."""
    script_words = tokenize_script(script)
    duration = probe_duration(audio)
    info: dict = {"duration": duration}
    if whisper_available(model):
        try:
            heard = transcribe_whisper(audio, model)
            words, ratio = align(script_words, heard, duration)
            info.update(method="whisper.cpp", match_ratio=round(ratio, 3),
                        transcript=" ".join(w.text for w in heard))
            if ratio < 0.6:
                log.warning("voiceover matches the script only %.0f%%; captions may drift", ratio * 100)
            return words, info
        except (subprocess.CalledProcessError, OSError, ValueError) as e:
            log.warning("whisper failed (%s); using silence-based fallback", e)
    words = distribute(script_words, speech_segments(audio))
    info.update(method="silencedetect-fallback", match_ratio=None)
    return words, info
