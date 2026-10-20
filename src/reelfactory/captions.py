"""Kinetic captions: chunk timed words into short punchy groups and draw them."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import svg
from .timing import Word, normalize

BREAK_AFTER = re.compile(r"[.,!?:;]$")
PAD_X = 0.75   # pill padding as a fraction of font size


@dataclass
class Chunk:
    words: list[Word]
    display: list[str]
    emphasis: list[bool]
    start: float
    end: float
    size: float
    xs: list[float] = field(default_factory=list)     # centre x of each word
    widths: list[float] = field(default_factory=list)

    @property
    def width(self) -> float:
        return (self.xs[-1] + self.widths[-1] / 2) - (self.xs[0] - self.widths[0] / 2)

    def bounds(self, center_y: float) -> tuple[float, float, float, float]:
        """Outer box of the subtitle pill."""
        pad = self.size * PAD_X
        x0 = self.xs[0] - self.widths[0] / 2 - pad
        x1 = self.xs[-1] + self.widths[-1] / 2 + pad
        return x0, center_y - self.size * 1.05, x1, center_y + self.size * 0.6


def display_text(word: str, uppercase: bool) -> str:
    w = re.sub(r'["“”]', "", word).rstrip(".,;:")
    return w.upper() if uppercase else w


def is_emphasis(word: str, terms: list[str]) -> bool:
    n = normalize(word)
    for t in terms:
        tn = normalize(t)
        if n == tn or (len(tn) >= 4 and n.startswith(tn)):
            return True
    return False


def build_chunks(words: list[Word], style: dict, emphasis_terms: list[str]) -> list[Chunk]:
    cs = style["captions"]
    font_file = style["fonts"]["caption"]["file"]
    size, max_w, max_words = cs["font_size"], cs["max_width"], cs["max_words"]
    space = size * cs.get("word_gap", 0.3)

    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            trial = " ".join(display_text(x.text, cs["uppercase"]) for x in cur + [w])
            too_wide = svg.text_width(trial, font_file, size) > max_w
            gap = w.start - cur[-1].end > 0.45
            if len(cur) >= max_words or too_wide or gap or BREAK_AFTER.search(cur[-1].text):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)

    chunks: list[Chunk] = []
    for g in groups:
        disp = [display_text(w.text, cs["uppercase"]) for w in g]
        sz = size
        while True:
            widths = [svg.text_width(d, font_file, sz) for d in disp]
            total = sum(widths) + space * (sz / size) * (len(disp) - 1)
            if total <= max_w or sz <= size * 0.55:
                break
            sz *= 0.92
        x = style["width"] / 2 - total / 2
        xs = []
        for wd in widths:
            xs.append(x + wd / 2)
            x += wd + space * (sz / size)
        chunks.append(Chunk(g, disp, [is_emphasis(w.text, emphasis_terms) for w in g],
                            start=max(g[0].start - 0.05, 0), end=g[-1].end + 0.35,
                            size=sz, xs=xs, widths=widths))
    # each chunk holds until the next one starts (unless there is a long pause)
    for a, b in zip(chunks, chunks[1:]):
        a.end = b.start if b.start - a.end < 0.6 else a.end
        a.end = min(a.end, b.start)
    return chunks


def active_chunk(chunks: list[Chunk], t: float) -> Chunk | None:
    for c in chunks:
        if c.start <= t < c.end:
            return c
    return None


def render(t: float, chunks: list[Chunk], style: dict) -> str:
    """Calm subtitle pill: words brighten as they are spoken, key words in accent."""
    c = active_chunk(chunks, t)
    if c is None:
        return ""
    cs, col = style["captions"], style["colors"]
    if cs.get("mode") == "kinetic":
        return render_kinetic(t, c, style)
    font = style["fonts"]["caption"]
    cy = cs["center_y"]
    enter = svg.ease_out_cubic(svg.progress(t, c.start, 0.18))
    x0, y0, x1, y1 = c.bounds(cy)
    out = [svg.rect(x0, y0, x1 - x0, y1 - y0, rx=(y1 - y0) / 2, fill=col.get("caption_bg", "#ffffff"), opacity=0.92,
                    stroke=col["line"], stroke_width=2)]
    for w, disp, emph, x, wd in zip(c.words, c.display, c.emphasis, c.xs, c.widths):
        p = svg.progress(t, w.start - 0.04, 0.14)
        op = svg.lerp(cs["upcoming_opacity"], 1.0, p)
        fill = col["accent"] if (emph and p > 0) else col["ink"]
        out.append(svg.text(x, cy, disp, font, c.size, fill=fill, opacity=round(op, 3)))
    return svg.group(out, transform=f"translate(0 {(1 - enter) * 10:.2f})", opacity=enter)


def render_kinetic(t: float, c: Chunk, style: dict) -> str:
    """Big bold words that pop in exactly as they are spoken; key words sit in an accent pill."""
    cs, col = style["captions"], style["colors"]
    font = style["fonts"]["caption"]
    cy = cs["center_y"]
    out = []
    for w, disp, emph, x, wd in zip(c.words, c.display, c.emphasis, c.xs, c.widths):
        p = svg.progress(t, w.start - 0.06, 0.2)
        if p <= 0:
            continue
        s = svg.ease_out_back(p)
        parts = []
        if emph:
            pw, ph = wd + c.size * 0.5, c.size * 1.18
            parts.append(svg.rect(x - pw / 2, cy - c.size * 0.86, pw, ph, rx=c.size * 0.24, fill=col["accent"],
                                  transform=f"rotate(-2 {x:.1f} {cy:.1f})"))
        parts.append(svg.text(x, cy, disp, font, c.size, fill=col.get("caption_ink", "#ffffff"), stroke="#0b0d14",
                              stroke_width=0 if emph else c.size * 0.14, paint_order="stroke", stroke_linejoin="round"))
        out.append(svg.group(parts, transform=svg.scale_about(x, cy - c.size * 0.3, max(s, 0.001)), opacity=min(1.0, p * 3)))
    return svg.group(out, opacity=1 - svg.progress(t, c.end - 0.12, 0.12))
