"""Frame compositor + parallel SVG rasterisation + FFmpeg encode."""
from __future__ import annotations

import logging
import math
import os
import shutil
import subprocess
import time
from multiprocessing import Pool
from pathlib import Path

from PIL import Image

from . import captions as cap
from . import scenes as sc
from . import svg
from .paths import Paths
from .timeline import Timeline

log = logging.getLogger(__name__)

# worker globals (set by _init in each process)
_TL: Timeline | None = None
_STYLE: dict | None = None
_ENV: dict | None = None
_DIR: Path | None = None


def frame_svg(t: float, tl: Timeline, style: dict, show_captions: bool = True) -> str:
    W, H = style["width"], style["height"]
    T = style.get("transition_seconds", 0.28)
    i = tl.scene_at(t)
    cur = tl.scenes[i]
    layers = [sc.background(t, style)]

    def draw(idx: int) -> str:
        s = tl.scenes[idx]
        return sc.SCENES[s.type](t - s.start, s.dur, s.params, style)

    in_tr = i > 0 and t < cur.start + T
    if in_tr:
        e = (t - cur.start) / T
        layers += transition(cur.params.get("transition") or ("zoom" if cur.type == "story" else "fade"),
                             e, draw(i - 1), draw(i), W, H)
    else:
        layers.append(draw(i))
    if hasattr(sc, "chrome"):
        layers.append(sc.chrome(style))
    kinetic = style["captions"].get("mode") == "kinetic"
    if show_captions and not _title_on(cur, t - cur.start) and not (kinetic and cur.type == "endcard"):
        layers.append(cap.render(t, tl.chunks, style))
    return svg.document(W, H, sc.defs(style), "".join(layers))


def _title_on(scene, lt: float) -> bool:
    """Story scenes hide the captions while their big title is on screen."""
    if scene.type != "story":
        return False
    from . import story
    win = story.title_window(scene.params)
    return bool(win and win[0] <= lt < win[1])


def transition(kind: str, e: float, old: str, new: str, W: int, H: int) -> list[str]:
    """Hand-off between two beats; ``e`` runs 0..1 over the transition."""
    io = svg.ease_in_out_cubic(svg.clamp(e))
    if kind == "cut":
        return [new]
    if kind == "whip":                      # fast horizontal push with a ghosted smear
        return [svg.group(old, transform=f"translate({-W * io:.1f} 0)"),
                svg.group(new, transform=f"translate({W * 0.35 * (1 - io):.1f} 0)", opacity=0.35 * (1 - io)) if io < 1 else "",
                svg.group(new, transform=f"translate({W * (1 - io):.1f} 0)")]
    if kind == "iris":                      # the new beat opens in a growing circle
        r = svg.ease_in_out_cubic(svg.clamp(e)) * math.hypot(W, H) * 0.6
        cid = f"iris{int(e * 1000)}"
        return [old, f'<clipPath id="{cid}"><circle cx="{W / 2}" cy="{H * 0.52:.0f}" r="{max(r, 0.1):.1f}"/></clipPath>',
                svg.group(new, clip_path=f"url(#{cid})")]
    if kind == "zoom":                      # old beat rushes past the camera, new one settles in
        out_e = svg.ease_in_out_cubic(svg.clamp(e * 1.4))
        in_e = svg.ease_out_cubic(svg.clamp((e - 0.25) / 0.75))
        return [svg.group(old, opacity=1 - out_e, transform=svg.scale_about(W / 2, H * 0.52, 1 + 0.35 * out_e)),
                svg.group(new, opacity=in_e, transform=svg.scale_about(W / 2, H * 0.52, 0.9 + 0.1 * in_e))]
    # calm hand-off: old beat fades and lifts away, new beat settles in
    out_e = svg.ease_in_out_cubic(svg.clamp(e * 1.6))
    return [svg.group(old, opacity=1 - out_e, transform=f"translate(0 {-30 * out_e:.1f})"),
            svg.group(new, opacity=svg.ease_out_cubic(svg.clamp((e - 0.35) / 0.65)))]


def rsvg_env(paths: Paths) -> dict:
    env = dict(os.environ)
    env["FONTCONFIG_FILE"] = str(paths.fontconfig)
    # On macOS Pango defaults to CoreText and silently ignores our bundled fonts.
    env["PANGOCAIRO_BACKEND"] = "fontconfig"
    return env


def font_check(paths: Paths, style: dict) -> dict[str, bool]:
    """True per font role if rsvg really uses that font (not a silent fallback)."""
    import tempfile

    def png(family: str, weight) -> bytes:
        doc = (f'<svg xmlns="http://www.w3.org/2000/svg" width="700" height="120"><rect width="700" height="120" fill="#fff"/>'
               f'<text x="10" y="90" font-family="{family}" font-weight="{weight}" font-size="72">Hamburg 1fiq</text></svg>')
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "f.png"
            rasterize(doc, out, rsvg_env(paths))
            return out.read_bytes()

    results = {}
    for role, f in style["fonts"].items():
        results[role] = png(f["family"], f["weight"]) != png("NoSuchFontXYZ", f["weight"])
    return results


def rasterize(svg_text: str, out_png: Path, env: dict) -> None:
    subprocess.run(["rsvg-convert", "-f", "png", "-o", str(out_png)], input=svg_text.encode("utf-8"),
                   env=env, check=True, capture_output=True)


def _init(tl: Timeline, style: dict, env: dict, frame_dir: Path, font_dir: Path) -> None:
    global _TL, _STYLE, _ENV, _DIR
    _TL, _STYLE, _ENV, _DIR = tl, style, env, frame_dir
    svg.set_font_dir(font_dir)


def _render_one(n: int) -> int:
    t = n / _STYLE["fps"]
    rasterize(frame_svg(t, _TL, _STYLE), _DIR / f"{n:05d}.png", _ENV)
    return n


def render_frames(tl: Timeline, style: dict, paths: Paths, frame_dir: Path, workers: int | None = None) -> int:
    if frame_dir.exists():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True)
    n_frames = int(round(tl.duration * style["fps"]))
    workers = workers or int(os.environ.get("REELFACTORY_WORKERS", os.cpu_count() or 4))
    t0 = time.time()
    with Pool(workers, initializer=_init, initargs=(tl, style, rsvg_env(paths), frame_dir, paths.fonts)) as pool:
        for k, _ in enumerate(pool.imap_unordered(_render_one, range(n_frames), chunksize=4), 1):
            if k % 150 == 0 or k == n_frames:
                log.info("frames %d/%d (%.1fs)", k, n_frames, time.time() - t0)
    return n_frames


def encode(frame_dir: Path, audio_wav: Path, out_mp4: Path, fps: int, duration: float) -> Path:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_mp4.with_suffix(".partial.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", str(frame_dir / "%05d.png"),
           "-i", str(audio_wav), "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-r", str(fps), "-g", str(fps * 2),
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-t", f"{duration:.3f}", "-movflags", "+faststart", str(tmp)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    tmp.replace(out_mp4)
    return out_mp4


def _save_jpg(svg_text: str, paths: Paths, out_jpg: Path) -> Path:
    svg.set_font_dir(paths.fonts)
    png = out_jpg.with_suffix(".png")
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    rasterize(svg_text, png, rsvg_env(paths))
    Image.open(png).convert("RGB").save(out_jpg, quality=92)
    png.unlink()
    return out_jpg


def cover(tl: Timeline, style: dict, paths: Paths, out_jpg: Path, t: float = 1.4) -> Path:
    """A still frame of the video (no captions)."""
    return _save_jpg(frame_svg(t, tl, style, show_captions=False), paths, out_jpg)


def thumbnail(params: dict, style: dict, paths: Paths, out_jpg: Path) -> Path:
    """The designed Reel cover (big headline, grid-safe); upload it as the cover in Instagram."""
    svg.set_font_dir(paths.fonts)                  # the headline is measured while laying out
    return _save_jpg(sc.thumbnail(params, style), paths, out_jpg)


def thumbnail_params(sb: dict) -> dict:
    """The storyboard's ``thumbnail`` block, else the first card's label and headline."""
    first = (sb.get("scenes") or [{}])[0].get("params", {})
    out = {"label": first.get("label", ""), "headline": first.get("headline", sb.get("title", "")),
           **(sb.get("thumbnail") or {})}
    if out.get("actor"):                    # story covers draw a character in its set
        out["_cast"] = sb.get("cast") or {}
        out.setdefault("set", first.get("set", "stage"))
    return out


def still_grid(stills: list[Path], labels: list[str], out: Path, cols: int = 3) -> Path:
    """Lay full-size frame PNGs out as one phone-friendly grid image."""
    from PIL import ImageDraw

    tw, th = 360, 640
    stills = stills[:9] or []
    rows = max(1, (len(stills) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * 12, rows * th + (rows + 1) * 12), "#ffffff")
    for k, (p, label) in enumerate(zip(stills, labels)):
        x, y = 12 + (k % cols) * (tw + 12), 12 + (k // cols) * (th + 12)
        sheet.paste(Image.open(p).convert("RGB").resize((tw, th)), (x, y))
        d = ImageDraw.Draw(sheet)
        d.rectangle(d.textbbox((x + 10, y + 10), label), fill="#ffffff")   # readable on dark scenes too
        d.text((x + 10, y + 10), label, fill="#2a211c")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=88)
    return out


def contact_sheet(mp4: Path, times: list[float], out: Path, cols: int = 3) -> Path:
    """Grid of stills (one per scene) for a quick visual check, e.g. on your phone."""
    import tempfile

    times = times[:6] or [0.5]
    with tempfile.TemporaryDirectory() as td:
        stills = []
        for k, t in enumerate(times):
            p = Path(td) / f"{k}.png"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(mp4), "-frames:v", "1",
                            str(p)], check=True)
            stills.append(p)
        return still_grid(stills, [f"{k + 1}  {t:.1f}s" for k, t in enumerate(times)], out, cols)
