"""Post-render checks: integrity, format, duration, audio, captions, assets."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageStat


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    severity: str = "error"   # "error" fails the job, "warn" only flags it

    def line(self) -> str:
        mark = "PASS" if self.ok else ("WARN" if self.severity == "warn" else "FAIL")
        return f"- [{mark}] **{self.name}**: {self.detail}"


def ffprobe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def mean_volume(path: Path) -> float:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-map", "0:a", "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else -99.0


def decode_errors(path: Path) -> str:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    return r.stderr.strip()


def sample_frames(path: Path, times: list[float], out_dir: Path) -> list[Path]:
    out = []
    for k, t in enumerate(times):
        p = out_dir / f"sample_{k}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", str(p)],
                       check=True)
        out.append(p)
    return out


def validate_video(mp4: Path, style: dict, expected_duration: float | None = None,
                   timeline=None, required_assets: list[Path] | None = None) -> list[Check]:
    checks: list[Check] = []
    if not mp4.exists() or mp4.stat().st_size == 0:
        return [Check("file exists", False, f"{mp4} missing or empty")]
    checks.append(Check("file exists", True, f"{mp4.name} ({mp4.stat().st_size / 1e6:.1f} MB)"))
    try:
        info = ffprobe(mp4)
    except subprocess.CalledProcessError as e:
        return checks + [Check("ffprobe", False, e.stderr or "unreadable")]
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    W, H, fps = style["width"], style["height"], style["fps"]
    if v is None:
        return checks + [Check("video stream", False, "no video stream")]
    checks.append(Check("resolution", (v["width"], v["height"]) == (W, H), f"{v['width']}x{v['height']} (want {W}x{H})"))
    checks.append(Check("codec", v["codec_name"] == "h264" and v.get("pix_fmt") == "yuv420p",
                        f"{v['codec_name']} / {v.get('pix_fmt')}"))
    num, den = (int(x) for x in v["r_frame_rate"].split("/"))
    checks.append(Check("frame rate", abs(num / den - fps) < 0.01, f"{num / den:.2f} fps"))
    dur = float(info["format"]["duration"])
    if expected_duration is not None:
        checks.append(Check("duration", abs(dur - expected_duration) <= 0.3,
                            f"{dur:.2f}s (expected {expected_duration:.2f}s ±0.3)"))
    checks.append(Check("reel length", 3 <= dur <= 90, f"{dur:.1f}s within 3–90s", severity="warn"))
    if a is None:
        checks.append(Check("audio stream", False, "no audio stream"))
    else:
        checks.append(Check("audio stream", a["codec_name"] == "aac", f"{a['codec_name']} {a.get('sample_rate')} Hz"))
        mv = mean_volume(mp4)
        checks.append(Check("audio level", mv > -40, f"mean volume {mv:.1f} dB (silent if < -40)"))
    errs = decode_errors(mp4)
    checks.append(Check("decode integrity", not errs, errs[:300] if errs else "full decode, no errors"))
    with tempfile.TemporaryDirectory() as td:
        times = [dur * f for f in (0.05, 0.3, 0.55, 0.8, 0.97)]
        blank = []
        for t, p in zip(times, sample_frames(mp4, times, Path(td))):
            st = ImageStat.Stat(Image.open(p).convert("L"))
            if st.stddev[0] < 4:
                blank.append(f"{t:.1f}s")
        checks.append(Check("visual content", not blank, "blank frames at " + ", ".join(blank) if blank else
                            "sampled frames all have visible content"))
    if timeline is not None:
        checks += validate_timeline(timeline, style)
    for p in required_assets or []:
        checks.append(Check(f"asset {p.name}", p.exists(), str(p)))
    return checks


def validate_timeline(tl, style: dict) -> list[Check]:
    out = []
    sz = style["safe_zone"]
    cy = style["captions"]["center_y"]
    bad_time, bad_box, overlap = [], [], []
    for k, c in enumerate(tl.chunks):
        if c.start < 0 or c.end > tl.duration + 0.01 or c.end <= c.start:
            bad_time.append(k)
        x0, y0, x1, y1 = c.bounds(cy)
        if x0 < sz["left"] or x1 > sz["right"] or y0 < sz["top"] or y1 > sz["bottom"]:
            bad_box.append(" ".join(c.display))
    for a, b in zip(tl.chunks, tl.chunks[1:]):
        if a.end > b.start + 1e-6:
            overlap.append(" ".join(a.display))
    out.append(Check("caption timing", not bad_time and not overlap,
                     f"{len(tl.chunks)} chunks, in range and non-overlapping" if not (bad_time or overlap)
                     else f"out of range: {bad_time}, overlapping: {overlap[:3]}"))
    out.append(Check("caption safe zone", not bad_box,
                     "all captions inside the IG safe zone" if not bad_box else f"outside: {bad_box[:3]}"))
    short = [s.type for s in tl.scenes if s.dur < 0.8]
    out.append(Check("scene lengths", not short, "all scenes ≥ 0.8s" if not short else f"very short: {short}", severity="warn"))
    for w in tl.warnings:
        out.append(Check("timeline", False, w, severity="warn"))
    return out


def passed(checks: list[Check]) -> bool:
    return all(c.ok or c.severity == "warn" for c in checks)


def report_md(idea_id: str, checks: list[Check], extra: dict) -> str:
    status = "PASS" if passed(checks) else "FAIL"
    lines = [f"# Review report: {idea_id}", "", f"**Validation: {status}**", ""]
    lines += [c.line() for c in checks]
    lines += ["", "## Timing", f"- Method: {extra.get('method')}",
              f"- Script match ratio: {extra.get('match_ratio')}"]
    if extra.get("transcript"):
        lines += [f"- Heard (whisper): _{extra['transcript']}_"]
    lines += ["", "## Claims to check before publishing"]
    for cl in extra.get("claims", []):
        lines.append(f"- [{cl.get('status', '?').upper()}] {cl['text']} {('— ' + cl['note']) if cl.get('note') else ''}")
    if not extra.get("sources"):
        lines.append("- ⚠️ No source links attached to this storyboard yet.")
    lines += ["", "## Human review checklist",
              "- [ ] Watch the full video with sound on a phone",
              "- [ ] Captions match what you said",
              "- [ ] Every factual claim is sourced or clearly framed as general/illustrative",
              "- [ ] Caption text reviewed in caption.txt",
              "- [ ] Publish manually (nothing is auto-posted)"]
    return "\n".join(lines) + "\n"
