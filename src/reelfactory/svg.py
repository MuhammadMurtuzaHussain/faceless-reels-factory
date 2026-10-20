"""Tiny SVG building helpers, easing curves and font measurement.

Everything here returns plain strings so frames stay cheap to build and easy
to inspect (write any frame's SVG to disk and open it in a browser).
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import ImageFont

# ---------------------------------------------------------------- easing


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def progress(t: float, start: float, dur: float) -> float:
    """Linear 0..1 progress of t through [start, start+dur]."""
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    return clamp((t - start) / dur)


def ease_out_cubic(p: float) -> float:
    p = clamp(p)
    return 1 - (1 - p) ** 3


def ease_in_cubic(p: float) -> float:
    p = clamp(p)
    return p ** 3


def ease_in_out_cubic(p: float) -> float:
    p = clamp(p)
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def ease_out_expo(p: float) -> float:
    p = clamp(p)
    return 1.0 if p >= 1 else 1 - 2 ** (-10 * p)


def ease_out_back(p: float, s: float = 1.70158) -> float:
    p = clamp(p)
    return 1 + (s + 1) * (p - 1) ** 3 + s * (p - 1) ** 2


def pulse(t: float, period: float) -> float:
    """0..1 sine pulse."""
    return 0.5 - 0.5 * math.cos(2 * math.pi * t / period)


# ---------------------------------------------------------------- fonts

_FONT_DIR: Path | None = None


def set_font_dir(path: Path) -> None:
    global _FONT_DIR
    _FONT_DIR = path
    _font.cache_clear()


@lru_cache(maxsize=64)
def _font(file: str, size: int) -> ImageFont.FreeTypeFont:
    if _FONT_DIR is None:
        raise RuntimeError("svg.set_font_dir() must be called before measuring text")
    return ImageFont.truetype(str(_FONT_DIR / file), size)


def text_width(text: str, font_file: str, size: float, letter_spacing: float = 0) -> float:
    w = _font(font_file, int(round(size))).getlength(text)
    return w * (size / int(round(size))) + letter_spacing * max(len(text) - 1, 0)


# ---------------------------------------------------------------- elements


def f(x: float) -> str:
    """Compact number formatting."""
    return f"{x:.2f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def attrs(**kw) -> str:
    out = []
    for k, v in kw.items():
        if v is None:
            continue
        k = k.rstrip("_").replace("_", "-")
        if isinstance(v, float):
            v = f(v)
        out.append(f'{k}="{v}"')
    return " ".join(out)


def rect(x, y, w, h, rx=0, **kw) -> str:
    return f"<rect {attrs(x=x, y=y, width=max(w, 0), height=max(h, 0), rx=rx, **kw)}/>"


def circle(cx, cy, r, **kw) -> str:
    return f"<circle {attrs(cx=cx, cy=cy, r=max(r, 0), **kw)}/>"


def line(x1, y1, x2, y2, **kw) -> str:
    return f"<line {attrs(x1=x1, y1=y1, x2=x2, y2=y2, **kw)}/>"


def path(d: str, **kw) -> str:
    return f"<path {attrs(d=d, **kw)}/>"


def text(x, y, content: str, font: dict, size: float, fill="#fff", anchor="middle",
         letter_spacing: float = 0, **kw) -> str:
    return (f"<text {attrs(x=x, y=y, font_family=font['family'], font_weight=font['weight'], font_size=size, fill=fill, text_anchor=anchor, letter_spacing=letter_spacing or None, **kw)}>"
            f"{escape(content)}</text>")


def group(children, transform: str | None = None, opacity: float | None = None, **kw) -> str:
    if opacity is not None and opacity <= 0.001:
        return ""
    body = "".join(c for c in children if c) if not isinstance(children, str) else children
    if not body:
        return ""
    op = None if opacity is None or opacity >= 0.999 else round(opacity, 3)
    return f"<g {attrs(transform=transform, opacity=op, **kw)}>{body}</g>"


def scale_about(cx: float, cy: float, s: float) -> str:
    return f"translate({f(cx)} {f(cy)}) scale({s:.4f}) translate({f(-cx)} {f(-cy)})"


def document(width: int, height: int, defs: str, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><defs>{defs}</defs>{body}</svg>')
