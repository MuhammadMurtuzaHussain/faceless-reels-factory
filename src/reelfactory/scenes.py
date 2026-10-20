"""Light editorial scene template (calm, minimal, original SVG graphics).

Every beat is a ``card`` scene: a cream headline card (small label, serif
headline with *accent* words, optional sub line) plus one simple visual below
it. Visuals are small UI mock-ups that reveal gently on cue words.

Scene functions are ``fn(lt, dur, params, style) -> svg fragment`` with ``lt``
= seconds since the scene started. They must tolerate ``lt > dur`` (they keep
drawing during the outgoing fade). Anchored params (``at`` / ``*_at``) arrive
resolved to local seconds, or None when unresolved.
"""
from __future__ import annotations

import base64
import re
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from . import svg
from .svg import (circle, ease_in_out_cubic, ease_out_back, ease_out_cubic, group, lerp, line, path, progress, rect,
                  scale_about, text)

W, H = 1080, 1920
CX = W / 2
CARD_X, CARD_W = 90, 900
PAD = 60


def at(params: dict, key: str, fallback):
    v = params.get(key)
    return fallback if v is None else v


def appear(lt: float, t0: float, dur: float = 0.45, dy: float = 22) -> tuple[float, str]:
    """(opacity, transform) for a gentle fade + rise starting at t0."""
    e = ease_out_cubic(progress(lt, t0, dur))
    return e, f"translate(0 {dy * (1 - e):.1f})"


def reveal(lt: float, t0: float, children, dur: float = 0.45, dy: float = 22) -> str:
    e, tr = appear(lt, t0, dur, dy)
    return group(children, transform=tr, opacity=e) if e > 0 else ""


# ---------------------------------------------------------------- defs, background, chrome


def defs(style: dict) -> str:
    c = style["colors"]
    return (
        f'<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c["bg_top"]}"/>'
        f'<stop offset="1" stop-color="{c["bg_bottom"]}"/></linearGradient>'
        '<radialGradient id="light" cx="50%" cy="22%" r="60%"><stop offset="0" stop-color="#ffffff" stop-opacity="0.55"/>'
        '<stop offset="1" stop-color="#ffffff" stop-opacity="0"/></radialGradient>'
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="160%"><feGaussianBlur stdDeviation="22"/></filter>'
        + GLOWS
    )


def _glow(gid: str, col: str, op: float = 1.0) -> str:
    return (f'<radialGradient id="{gid}"><stop offset="0" stop-color="{col}" stop-opacity="{op}"/>'
            f'<stop offset="1" stop-color="{col}" stop-opacity="0"/></radialGradient>')


# soft lights shared by story scenes (radial gradients are far cheaper to rasterise than blur filters)
GLOWS = (_glow("g-warm", "#ffc27a") + _glow("g-cool", "#7fb6ff") + _glow("g-hot", "#ff6a2a") +
         _glow("g-danger", "#ff4d5e") + _glow("g-white", "#ffffff", 0.8) + _glow("g-floor", "#ffe2b0", 0.45) +
         '<linearGradient id="g-cone" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffe7bf" stop-opacity="0.75"/>'
         '<stop offset="1" stop-color="#ffe7bf" stop-opacity="0"/></linearGradient>'
         '<radialGradient id="g-vig" cx="50%" cy="48%" r="75%"><stop offset="0.55" stop-color="#000" stop-opacity="0"/>'
         '<stop offset="1" stop-color="#000" stop-opacity="0.55"/></radialGradient>')


def background(t: float, style: dict) -> str:
    return rect(0, 0, W, H, fill="url(#bg)") + rect(0, 0, W, H, fill="url(#light)")


def chrome(style: dict) -> str:
    """Static brand mark bottom-left (inside the Instagram safe zone)."""
    c, ui = style["colors"], style["fonts"]["body"]
    y = style.get("chrome_y", 1488)
    return group([circle(108, y, 16, fill=c["accent"]),
                  text(136, y + 10, style.get("handle", ""), ui, 28, anchor="start", fill=c["muted"])])


def card(x, y, w, h, style, rx=36, fill=None) -> str:
    c = style["colors"]
    return (rect(x + 6, y + 22, w - 12, h, rx=rx, fill=c["shadow"], opacity=0.16, filter="url(#shadow)") +
            rect(x, y, w, h, rx=rx, fill=fill or c["card"], stroke=c["line"], stroke_width=2))


# ---------------------------------------------------------------- headline typesetting

TOKEN = re.compile(r"\*([^*]+)\*(\S*)|(\S+)")


def parse_rich(s: str) -> list[tuple[str, bool]]:
    """'Your data is *worth more*.' -> [(word, is_accent), ...]; trailing punctuation stays attached."""
    out = []
    for m in TOKEN.finditer(s):
        if m.group(1):
            words = m.group(1).split()
            out += [(w, True) for w in words]
            if m.group(2):                         # e.g. the '.' after *name*
                out.append(("\x00" + m.group(2), False))
        else:
            out.append((m.group(3), False))
    return out


def plain(words: list[tuple[str, bool]]) -> str:
    return " ".join(w for w, _ in words).replace(" \x00", "").replace("\x00", "")


def wrap_rich(s: str, font_file: str, size: float, max_w: float) -> list[list[tuple[str, bool]]]:
    """Greedy wrap, then narrow the measure as far as possible without adding a line (balanced rag)."""
    best = _greedy(s, font_file, size, max_w)
    w = max_w
    while w > max_w * 0.55 and len(best) > 1:
        trial = _greedy(s, font_file, size, w - 20)
        if len(trial) > len(best):
            break
        best, w = trial, w - 20
    return best


def _greedy(s: str, font_file: str, size: float, max_w: float) -> list[list[tuple[str, bool]]]:
    lines, cur = [], []
    for w in parse_rich(s):
        trial = plain(cur + [w])
        if cur and svg.text_width(trial, font_file, size) > max_w:
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def rich_line(x: float, y: float, words: list[tuple[str, bool]], font: dict, size: float, style: dict) -> str:
    c = style["colors"]
    spans = []
    for i, (w, acc) in enumerate(words):
        glued = w.startswith("\x00")
        sp = w[1:] if glued else (" " if i else "") + w
        spans.append(f'<tspan fill="{c["accent"] if acc else c["ink"]}">{escape(sp)}</tspan>')
    return (f'<text x="{x}" y="{y:.1f}" font-family="{font["family"]}" font-weight="{font["weight"]}" '
            f'font-size="{size}" xml:space="preserve">{"".join(spans)}</text>')


def headline_layout(p: dict, style: dict) -> dict:
    hf = style["fonts"]["headline"]
    size = p.get("size", 80)
    inner = CARD_W - 2 * PAD
    lines = wrap_rich(p.get("headline", ""), hf["file"], size, inner)
    lines2 = wrap_rich(p["headline2"], hf["file"], size, inner) if p.get("headline2") else []
    n = max(len(lines), len(lines2), 1)
    lh = size * 1.1
    sub_h = 64 if p.get("sub") else 0
    h = PAD + 50 + n * lh + sub_h + PAD - 10
    return {"lines": lines, "lines2": lines2, "size": size, "lh": lh, "h": h, "y": p.get("card_y", 270)}


def headline_card(lt: float, dur: float, p: dict, style: dict, step: str) -> tuple[str, float]:
    """Draw the headline card; returns (svg, bottom y)."""
    c, hf, ui, sf = style["colors"], style["fonts"]["headline"], style["fonts"]["ui"], style["fonts"]["sub"]
    L = headline_layout(p, style)
    y0 = L["y"]
    x = CARD_X + PAD
    out = [card(CARD_X, y0, CARD_W, L["h"], style)]
    out.append(reveal(lt, 0.05, [
        text(x, y0 + PAD + 14, p.get("label", "").upper(), ui, 28, anchor="start", fill=c["accent"], letter_spacing=4),
        text(CARD_X + CARD_W - PAD, y0 + PAD + 14, step, ui, 26, anchor="end", fill=c["muted"], letter_spacing=2)]))
    base = y0 + PAD + 50 + L["size"] * 0.92
    swap_t = at(p, "swap_at", None) if L["lines2"] else None
    sw = ease_in_out_cubic(progress(lt, swap_t, 0.4)) if swap_t is not None else 0.0
    if sw < 1:
        first = [reveal(lt, 0.12 + i * 0.09, rich_line(x, base + i * L["lh"], ln, hf, L["size"], style))
                 for i, ln in enumerate(L["lines"])]
        out.append(group(first, opacity=1 - sw, transform=f"translate(0 {-16 * sw:.1f})" if sw else None))
    if sw > 0:
        second = [rich_line(x, base + i * L["lh"], ln, hf, L["size"], style) for i, ln in enumerate(L["lines2"])]
        out.append(group(second, opacity=sw, transform=f"translate(0 {16 * (1 - sw):.1f})"))
    if p.get("sub"):
        n = max(len(L["lines"]), len(L["lines2"]), 1)
        out.append(reveal(lt, 0.35, text(x, base + (n - 1) * L["lh"] + 70, p["sub"], sf, 40, anchor="start",
                                          fill=c["muted"])))
    return "".join(out), y0 + L["h"]


# ---------------------------------------------------------------- small icons


def glyph(name: str, cx: float, cy: float, s: float, color: str) -> str:
    sw = max(s * 0.1, 2.5)
    k = dict(fill="none", stroke=color, stroke_width=sw, stroke_linecap="round", stroke_linejoin="round")
    if name == "user":
        return circle(cx, cy - s * 0.16, s * 0.18, **k) + path(
            f"M{cx - s*0.32} {cy + s*0.34}Q{cx} {cy - s*0.04} {cx + s*0.32} {cy + s*0.34}", **k)
    if name == "pin":
        return path(f"M{cx} {cy + s*0.36}C{cx - s*0.3} {cy + s*0.04} {cx - s*0.28} {cy - s*0.12} {cx - s*0.28} {cy - s*0.12}"
                    f"A{s*0.28} {s*0.28} 0 1 1 {cx + s*0.28} {cy - s*0.12}C{cx + s*0.28} {cy + s*0.04} {cx} {cy + s*0.36} {cx} {cy + s*0.36}Z", **k)
    if name == "repeat":
        r = s * 0.26
        return path(f"M{cx + r} {cy}A{r} {r} 0 1 1 {cx} {cy - r}", **k) + path(
            f"M{cx - s*0.07} {cy - r - s*0.09}L{cx + s*0.03} {cy - r}L{cx - s*0.07} {cy - r + s*0.09}", **k)
    if name == "pause":
        return line(cx - s * 0.12, cy - s * 0.24, cx - s * 0.12, cy + s * 0.24, **k) + line(
            cx + s * 0.12, cy - s * 0.24, cx + s * 0.12, cy + s * 0.24, **k)
    if name == "moon":
        r = s * 0.28
        return path(f"M{cx + r*0.3} {cy - r}A{r} {r} 0 1 0 {cx + r} {cy + r*0.35}A{r*0.8} {r*0.8} 0 0 1 {cx + r*0.3} {cy - r}Z", **k)
    if name == "cart":
        return path(f"M{cx - s*0.34} {cy - s*0.26}h{s*0.1}l{s*0.1} {s*0.4}h{s*0.4}l{s*0.08} -{s*0.3}h-{s*0.52}", **k) + \
            circle(cx - s * 0.08, cy + s * 0.3, s * 0.05, fill=color) + circle(cx + s * 0.2, cy + s * 0.3, s * 0.05, fill=color)
    if name == "click":
        return path(f"M{cx - s*0.16} {cy - s*0.28}l{s*0.42} {s*0.16}l-{s*0.18} {s*0.06}l-{s*0.06} {s*0.18}Z", **k)
    if name == "heart":
        return path(f"M{cx} {cy + s*0.28}C{cx - s*0.5} {cy - s*0.04} {cx - s*0.22} {cy - s*0.42} {cx} {cy - s*0.14}"
                    f"C{cx + s*0.22} {cy - s*0.42} {cx + s*0.5} {cy - s*0.04} {cx} {cy + s*0.28}Z", **k)
    if name == "clock":
        return circle(cx, cy, s * 0.3, **k) + path(f"M{cx} {cy - s*0.16}V{cy}l{s*0.12} {s*0.08}", **k)
    if name == "cursor":
        return path(f"M{cx} {cy}L{cx} {cy + s}L{cx + s*0.28} {cy + s*0.74}L{cx + s*0.48} {cy + s*1.12}"
                    f"L{cx + s*0.62} {cy + s*1.05}L{cx + s*0.42} {cy + s*0.68}L{cx + s*0.76} {cy + s*0.68}Z",
                    fill="#2a211c", stroke="#ffffff", stroke_width=s * 0.07, stroke_linejoin="round")
    return circle(cx, cy, s * 0.22, **k)


def tile(cx, cy, s, color, name) -> str:
    return rect(cx - s / 2, cy - s / 2, s, s, rx=s * 0.26, fill=color) + glyph(name, cx, cy, s * 0.62, "#ffffff")


# ---------------------------------------------------------------- visuals (below the headline card)


def v_apps(lt, dur, v, style, y0):
    """App tiles quietly feed small dots into one 'Your profile' card."""
    c, sf = style["colors"], style["fonts"]["sub"]
    pal = [c["sage"], c["mustard"], c["slate"], c["accent"], c["plum"]]
    names = ["heart", "pin", "cart", "click", "clock"]
    ty, py = y0 + 100, y0 + 320
    out = []
    xs = [CX + (i - 2) * 160 for i in range(5)]
    for i, (x, col) in enumerate(zip(xs, pal)):
        if lt > 0.9:   # slow dots drifting from each app into the profile card
            q = ((lt - 0.9) / 1.8 + i * 0.21) % 1.0
            e = ease_in_out_cubic(q)
            out.append(circle(lerp(x, CX, e), lerp(ty + 70, py - 20, e), 9, fill=col, opacity=min(1, 4 * (1 - q)) * 0.9))
    for i, (x, col, nm) in enumerate(zip(xs, pal, names)):
        out.append(reveal(lt, 0.3 + i * 0.07, tile(x, ty, 112, col, nm)))
    cw, chh = 560, 170
    fill = 0.15 + 0.7 * ease_out_cubic(progress(lt, 0.8, max(dur - 1.0, 1)))
    prof = [card(CX - cw / 2, py, cw, chh, style, rx=30),
            circle(CX - cw / 2 + 80, py + 85, 44, fill=c["sand"]),
            glyph("user", CX - cw / 2 + 80, py + 85, 58, c["ink"]),
            text(CX - cw / 2 + 150, py + 76, "Your profile", sf, 40, anchor="start", fill=c["ink"]),
            rect(CX - cw / 2 + 150, py + 104, 340, 14, rx=7, fill=c["line"]),
            rect(CX - cw / 2 + 150, py + 104, 340 * fill, 14, rx=7, fill=c["accent"])]
    out.append(reveal(lt, 0.55, prof))
    return "".join(out)


def v_rows(lt, dur, v, style, y0):
    """List card; each row slides in on its cue word, newest row outlined."""
    c, ui, body = style["colors"], style["fonts"]["ui"], style["fonts"]["body"]
    rows = v.get("rows", [])
    n = max(len(rows), 1)
    times = [at(r, "at", 0.5 + i * (dur - 1) / n) for i, r in enumerate(rows)]
    rh, gap = 112, 18
    x, w = CARD_X + 20, CARD_W - 40
    pal = [c["slate"], c["accent"], c["sage"], c["mustard"], c["plum"]]
    out = []
    for i, (r, t0) in enumerate(zip(rows, times)):
        y = y0 + 60 + i * (rh + gap)
        e, tr = appear(lt, t0 - 0.05, 0.4, 26)
        if e <= 0:
            out.append(rect(x, y, w, rh, rx=26, fill="#ffffff", opacity=0.35, stroke=c["line"], stroke_width=2,
                            stroke_dasharray="8 10"))
            continue
        newest = all(lt < t for t in times[i + 1:])
        hl = (1 - progress(lt, t0 + 0.9, 0.5)) if newest else 0.0
        row = [rect(x, y, w, rh, rx=26, fill=c["card"], stroke=c["accent"] if hl > 0.05 else c["line"],
                    stroke_width=2 + 2 * hl),
               tile(x + 66, y + rh / 2, 64, pal[i % len(pal)], r.get("icon", "")),
               text(x + 124, y + 50, r["label"], ui, 36, anchor="start", fill=c["ink"]),
               text(x + 124, y + 86, r.get("detail", ""), body, 26, anchor="start", fill=c["muted"])]
        vw = svg.text_width(r.get("value", ""), ui["file"], 28) + 44
        row += [rect(x + w - 36 - vw, y + rh / 2 - 26, vw, 52, rx=26, fill=c["chip"]),
                text(x + w - 36 - vw / 2, y + rh / 2 + 10, r.get("value", ""), ui, 28, fill=c["ink"])]
        out.append(group(row, transform=tr, opacity=e))
    return "".join(out)


def v_connect(lt, dur, v, style, y0):
    """Scattered grey chips; on cue they light up and link to 'You'; then a prediction card."""
    c, ui, sf = style["colors"], style["fonts"]["ui"], style["fonts"]["sub"]
    t_conn = at(v, "connect_at", dur * 0.4)
    t_pred = at(v, "predict_at", dur * 0.65)
    conn = ease_out_cubic(progress(lt, t_conn, 0.6))
    labels = v.get("labels", ["Purchases", "Clicks", "Interests", "Routine"])
    icons = ["cart", "click", "heart", "clock"]
    pal = [c["mustard"], c["slate"], c["accent"], c["sage"]]
    cy = y0 + 250
    pos = [(CX - 250, cy - 150), (CX + 250, cy - 150), (CX - 250, cy + 150), (CX + 250, cy + 150)]
    out = []
    for i, (px, py) in enumerate(pos):          # connecting lines first (under the chips)
        lp = ease_out_cubic(progress(lt, t_conn + i * 0.08, 0.5))
        if lp > 0:
            out.append(line(CX, cy, lerp(CX, px, lp), lerp(cy, py, lp), stroke=c["ink"], stroke_width=4,
                            opacity=0.3, stroke_dasharray="2 12", stroke_linecap="round"))
    for i, ((px, py), lab, ic) in enumerate(zip(pos, labels, icons)):
        cw = 300
        col = pal[i] if conn > 0.5 else c["muted"]
        chip = [card(px - cw / 2, py - 48, cw, 96, style, rx=48),
                tile(px - cw / 2 + 50, py, 60, col, ic),
                text(px - cw / 2 + 96, py + 12, lab, ui, 32, anchor="start", fill=c["ink"])]
        out.append(group(reveal(lt, 0.3 + i * 0.08, chip), opacity=lerp(0.55, 1, conn)))
    you = [circle(CX, cy, 74, fill=c["card"], stroke=c["accent"] if conn > 0.5 else c["line"], stroke_width=4),
           glyph("user", CX, cy, 84, c["ink"])]
    out.append(reveal(lt, 0.2, you))
    pe, tr = appear(lt, t_pred, 0.45, 26)
    if pe > 0:
        py, pw = cy + 260, 560
        pred = [card(CX - pw / 2, py, pw, 190, style, rx=30),
                text(CX - pw / 2 + 40, py + 56, "PREDICTION", ui, 24, anchor="start", fill=c["accent"], letter_spacing=4),
                text(CX - pw / 2 + 40, py + 112, "Likely to buy", sf, 36, anchor="start", fill=c["ink"]),
                text(CX - pw / 2 + 40, py + 160, "Likely to click", sf, 36, anchor="start", fill=c["ink"])]
        for k, yy in enumerate((py + 100, py + 148)):
            ck = ease_out_cubic(progress(lt, t_pred + 0.3 + k * 0.25, 0.3))
            pred.append(group([circle(CX + pw / 2 - 60, yy, 20, fill=c["sage"]),
                               path(f"M{CX + pw/2 - 70} {yy}l7 8l14 -15", fill="none", stroke="#fff", stroke_width=4,
                                    stroke_linecap="round", stroke_linejoin="round")], opacity=ck))
        out.append(group(pred, transform=tr, opacity=pe))
    return "".join(out)


def v_feed(lt, dur, v, style, y0):
    """A simple feed; ads get tagged, then the feed re-sorts itself around you."""
    c, ui = style["colors"], style["fonts"]["ui"]
    t_ads = at(v, "ads_at", dur * 0.35)
    t_sort = at(v, "sort_at", dur * 0.65)
    fw, ph = 620, 150
    fx = CX - fw / 2
    pal = [c["sage"], c["mustard"], c["slate"]]
    order0, order1 = [0, 1, 2], [2, 0, 1]
    s = ease_in_out_cubic(progress(lt, t_sort, 0.6))
    out = [reveal(lt, 0.25, card(fx - 30, y0 + 40, fw + 60, 3 * (ph + 24) + 70, style, rx=40))]
    for k in range(3):
        y = lerp(y0 + 80 + order0.index(k) * (ph + 24), y0 + 80 + order1.index(k) * (ph + 24), s)
        post = [rect(fx, y, fw, ph, rx=24, fill="#ffffff", stroke=c["line"], stroke_width=2),
                rect(fx + 20, y + 20, 110, 110, rx=18, fill=pal[k], opacity=0.85),
                rect(fx + 156, y + 36, 300, 22, rx=11, fill=c["line"]),
                rect(fx + 156, y + 76, 220, 22, rx=11, fill=c["line"])]
        if k != 1:
            ae = ease_out_cubic(progress(lt, t_ads + k * 0.15, 0.35))
            if ae > 0:
                post.append(group([rect(fx + fw - 190, y + 18, 170, 46, rx=23, fill=c["accent"]),
                                   text(fx + fw - 105, y + 49, "Sponsored", ui, 24, fill="#ffffff")], opacity=ae))
        out.append(reveal(lt, 0.35 + k * 0.08, post))
    se = ease_out_cubic(progress(lt, t_sort + 0.3, 0.4))
    if se > 0:
        yy = y0 + 10     # chip sits on the feed card's top edge
        out.append(group([rect(CX - 150, yy, 300, 60, rx=30, fill=c["ink"]),
                          text(CX, yy + 40, "Sorted for you", ui, 28, fill="#ffffff")],
                         transform=f"translate(0 {12 * (1 - se):.1f})", opacity=se))
    return "".join(out)


def v_consent(lt, dur, v, style, y0):
    """A cookie dialog; a cursor drifts to 'Accept all' and hesitates."""
    c, ui, sf = style["colors"], style["fonts"]["ui"], style["fonts"]["sub"]
    t_q = at(v, "dim_at", dur * 0.5)
    dim = ease_in_out_cubic(progress(lt, t_q, 0.5))
    dw, dh = 780, 470
    dx, dy = CX - dw / 2, y0 + 60
    bx, by, bw, bh = dx + dw - 60 - 300, dy + dh - 60 - 96, 300, 96
    dlg = [card(dx, dy, dw, dh, style, rx=36),
           text(dx + 56, dy + 96, "We value your privacy", sf, 46, anchor="start", fill=c["ink"]),
           rect(dx + 56, dy + 140, 640, 20, rx=10, fill=c["line"]),
           rect(dx + 56, dy + 180, 560, 20, rx=10, fill=c["line"]),
           rect(dx + 56, dy + 220, 600, 20, rx=10, fill=c["line"]),
           rect(dx + 56, by, 260, bh, rx=48, fill="none", stroke=c["muted"], stroke_width=2.5),
           text(dx + 186, by + 60, "Manage", ui, 32, fill=c["muted"]),
           rect(bx, by, bw, bh, rx=48, fill=c["accent"]),
           text(bx + bw / 2, by + 60, v.get("button", "Accept all"), ui, 32, fill="#ffffff")]
    cp = ease_in_out_cubic(progress(lt, 0.6, 1.4))
    cx_, cy_ = lerp(dx + dw + 40, bx + bw * 0.86, cp), lerp(dy + dh + 260, by + bh * 0.72, cp)
    dlg.append(glyph("cursor", cx_, cy_, 64, c["ink"]))
    out = [group(reveal(lt, 0.3, dlg), opacity=1 - 0.65 * dim,
                 transform=scale_about(CX, dy + dh / 2, 1 - 0.04 * dim))]
    if v.get("follow"):
        fe, tr = appear(lt, max(t_q + 1.2, dur - 1.8), 0.5, 20)
        if fe > 0:
            label = f"Follow {style.get('handle', '')}"
            fw2 = svg.text_width(label, ui["file"], 36) + 100
            fy = dy + dh + 90
            out.append(group([rect(CX - fw2 / 2, fy, fw2, 90, rx=45, fill=c["ink"]),
                              text(CX, fy + 58, label, ui, 36, fill="#ffffff")], transform=tr, opacity=fe))
    return "".join(out)


@lru_cache(maxsize=4)
def _photo_uri(file: str) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(Path(file).read_bytes()).decode("ascii")


def avatar(cx: float, cy: float, r: float, style: dict, ring: float = 5) -> str:
    """Profile photo (style.profile.avatar) in the accent ring; a monogram when there's no photo."""
    c, hf = style["colors"], style["fonts"]["headline"]
    out = circle(cx, cy, r + ring * 1.8, fill="none", stroke=c["accent"], stroke_width=ring)
    photo = (style.get("profile") or {}).get("avatar")
    if photo and Path(photo).exists():
        cid = f"av{int(cx)}x{int(cy)}x{int(r)}"
        return out + (f'<clipPath id="{cid}"><circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}"/></clipPath>'
                      f'<image href="{_photo_uri(photo)}" x="{cx - r:.1f}" y="{cy - r:.1f}" width="{2 * r:.1f}" '
                      f'height="{2 * r:.1f}" preserveAspectRatio="xMidYMid slice" clip-path="url(#{cid})"/>')
    letter = style.get("handle", "@").lstrip("@")[:1].upper() or "•"
    return out + circle(cx, cy, r, fill=c["sand"]) + text(cx, cy + r * 0.36, letter, hf, r * 1.05, fill=c["ink"])


def centered_rich(y: float, s: str, font: dict, size: float, style: dict, max_w: float = CARD_W) -> tuple[str, int]:
    """A rich headline wrapped and centred on the frame; returns (svg, number of lines)."""
    lines = wrap_rich(s, font["file"], size, max_w)
    out = [rich_line(CX - svg.text_width(plain(ln), font["file"], size) / 2, y + i * size * 1.1, ln, font, size, style)
           for i, ln in enumerate(lines)]
    return "".join(out), len(lines)


def endcard_scene(lt: float, dur: float, p: dict, style: dict) -> str:
    """Closing page: your Instagram profile header, a Follow button a cursor taps, save/share nudges."""
    c, hf, sf, ui, body = (style["colors"], style["fonts"]["headline"], style["fonts"]["sub"], style["fonts"]["ui"],
                           style["fonts"]["body"])
    prof = style.get("profile") or {}
    t_tap = at(p, "follow_at", min(1.4, dur * 0.45))
    out = [reveal(lt, 0.05, text(CX, 240, p.get("label", "").upper(), ui, 28, fill=c["accent"], letter_spacing=5))]
    head, n = centered_rich(322, p.get("headline", ""), hf, p.get("size", 84), style)
    out.append(reveal(lt, 0.12, head))

    py = 322 + (n - 1) * p.get("size", 84) * 1.1 + 80          # profile card under the headline
    pw, ph = CARD_W, 666
    px = CX - pw / 2
    acy = py + 150
    pop = ease_out_back(progress(lt, 0.3, 0.55)) if lt > 0.3 else 0.0
    by, bh = py + ph - 52 - 104, 104
    press = 1 - 0.05 * (progress(lt, t_tap - 0.12, 0.12) - progress(lt, t_tap, 0.15))
    done = ease_out_cubic(progress(lt, t_tap, 0.3))
    bio = prof.get("bio") or [p.get("bio", "")]
    card_parts = [card(px, py, pw, ph, style, rx=44),
                  group(avatar(CX, acy, 100, style, ring=6), transform=scale_about(CX, acy, max(pop, 0.01)))]
    card_parts.append(reveal(lt, 0.45, [
        text(CX, acy + 170, prof.get("username", style.get("handle", "").lstrip("@")), ui, 46, fill=c["ink"]),
        text(CX, acy + 218, prof.get("name", ""), sf, 36, fill=c["muted"])]))
    card_parts.append(reveal(lt, 0.6, [text(CX, acy + 278 + i * 40, ln, body, 31, fill=c["ink"])
                                       for i, ln in enumerate(bio[:2])]))
    btn = [rect(px + 60, by, pw - 120, bh, rx=52, fill=c["accent"], opacity=1 - done),
           text(CX, by + 66, "Follow", ui, 40, fill="#ffffff", opacity=1 - done),
           rect(px + 60, by, pw - 120, bh, rx=52, fill=c["chip"], stroke=c["line"], stroke_width=2, opacity=done),
           text(CX - 24, by + 66, "Following", ui, 40, fill=c["ink"], opacity=done),
           path(f"M{CX + 96} {by + 52}l11 12l22 -24", fill="none", stroke=c["sage"], stroke_width=6,
                stroke_linecap="round", stroke_linejoin="round", opacity=done)]
    card_parts.append(reveal(lt, 0.75, group(btn, transform=scale_about(CX, by + bh / 2, press))))
    out.append(reveal(lt, 0.1, card_parts, dur=0.5, dy=30))

    cp = ease_in_out_cubic(progress(lt, max(0.6, t_tap - 0.9), 0.75))
    if cp > 0 and lt < t_tap + 0.9:
        gone = progress(lt, t_tap + 0.35, 0.5)
        cx_, cy_ = lerp(CX + 340, CX + 160, cp), lerp(by + 380, by + bh * 0.55, cp)
        out.append(group(glyph("cursor", cx_, cy_, 64, c["ink"]), opacity=1 - gone))

    chips = p.get("chips", ["Save it for later", "Send it to a friend"])
    gy = py + ph + 36
    widths = [svg.text_width(s, ui["file"], 30) + 70 for s in chips]
    x = CX - (sum(widths) + 24 * (len(chips) - 1)) / 2
    for k, (label, w) in enumerate(zip(chips, widths)):
        out.append(reveal(lt, t_tap + 0.45 + k * 0.15, [
            rect(x, gy, w, 76, rx=38, fill=c["card"], stroke=c["line"], stroke_width=2),
            text(x + w / 2, gy + 49, label, ui, 30, fill=c["ink"])]))
        x += w + 24
    return "".join(out)


VISUALS = {"apps": v_apps, "rows": v_rows, "connect": v_connect, "feed": v_feed, "consent": v_consent}


# ---------------------------------------------------------------- thumbnail (Reel cover)

GRID_TOP, GRID_BOTTOM = 240, 1680      # the 3:4 profile-grid crop of a 9:16 cover


def story_cover(p: dict, style: dict) -> str:
    """Cover for story reels: the set, the main character, a big bold headline (all inside the grid crop)."""
    from . import story
    c, ui = style["colors"], style["fonts"]["ui"]
    tf = style["fonts"].get("title") or style["fonts"]["headline"]
    a = dict(p["actor"])
    a.setdefault("el", "actor")
    a.setdefault("x", 540)
    a.setdefault("size", 1.25)
    a["at"] = 0.0
    scene = {"set": p.get("set", "stage"), "elements": [a] + list(p.get("props", [])), "_cast": p.get("_cast", {}),
             "camera": {"drift": 0, "zoom": p.get("zoom", 1.0), "focus": p.get("focus", [540, 1000])}}
    for k, v in (p.get("set_params") or {}).items():
        scene[k] = v
    body = story.story_scene(2.0, 4.0, scene, style)
    size = 132
    while size > 90:
        lines = wrap_rich(p.get("headline", ""), tf["file"], size, 940)
        if len(lines) <= 3:
            break
        size -= 8
    out = [background(0, style), body, rect(0, 0, W, 900, fill="url(#g-topfade)")]
    label = p.get("label", "").upper()
    y = GRID_TOP + 90
    if label:
        lw = svg.text_width(label, ui["file"], 30, letter_spacing=4) + 64
        out += [rect(CX - lw / 2, y, lw, 70, rx=35, fill=c["accent"]),
                text(CX, y + 46, label, ui, 30, fill="#ffffff", letter_spacing=4)]
        y += 70
    base = y + 60 + size * 0.85
    for i, ln in enumerate(lines):
        tw = svg.text_width(plain(ln), tf["file"], size)
        x = CX - tw / 2
        spans = []
        for k, (w, acc) in enumerate(ln):
            glued = w.startswith("\x00")
            sp = w[1:] if glued else (" " if k else "") + w
            spans.append(f'<tspan fill="{c["accent"] if acc else c["ink"]}">{escape(sp)}</tspan>')
        out.append(f'<text x="{x:.1f}" y="{base + i * size * 1.04:.1f}" font-family="{tf["family"]}" font-weight="{tf["weight"]}" '
                   f'font-size="{size}" stroke="#0b0d14" stroke-width="{size * 0.08:.1f}" paint-order="stroke" '
                   f'stroke-linejoin="round" xml:space="preserve">{"".join(spans)}</text>')
    hy = GRID_BOTTOM - 70
    out += [avatar(CARD_X + 34, hy, 26, style),
            text(CARD_X + 86, hy + 12, style.get("handle", ""), ui, 34, anchor="start", fill=c["ink"])]
    return svg.document(W, H, defs(style) + '<linearGradient id="g-topfade" x1="0" y1="0" x2="0" y2="1">'
                        '<stop offset="0" stop-color="#05070d" stop-opacity="0.85"/><stop offset="1" stop-color="#05070d" '
                        'stop-opacity="0"/></linearGradient>', "".join(out))


def thumbnail(p: dict, style: dict) -> str:
    """A full 1080x1920 cover. Everything important sits inside the 3:4 grid crop."""
    if p.get("actor"):
        return story_cover(p, style)
    c, hf, sf, ui = style["colors"], style["fonts"]["headline"], style["fonts"]["sub"], style["fonts"]["ui"]
    inner = CARD_W - 20
    size = 150
    while size > 96:                         # biggest type that keeps the headline to four lines
        lines = wrap_rich(p.get("headline", ""), hf["file"], size, inner)
        if len(lines) <= 4:
            break
        size -= 8
    lh = size * 1.04
    label = p.get("label", "").upper()
    lw = svg.text_width(label, ui["file"], 30, letter_spacing=4) + 64
    block = 76 + 64 + len(lines) * lh + (90 if p.get("sub") else 0)
    top = (GRID_TOP + GRID_BOTTOM) / 2 - block / 2 - 40
    out = [background(0, style),
           circle(930, top - 30, 230, fill=c["accent"], opacity=0.13),
           circle(960, top + block + 170, 120, fill=c["sage"], opacity=0.14)]
    if label:
        out += [rect(CARD_X, top, lw, 76, rx=38, fill=c["accent"]),
                text(CARD_X + lw / 2, top + 49, label, ui, 30, fill="#ffffff", letter_spacing=4)]
    base = top + 76 + 64 + size * 0.8
    out += [rich_line(CARD_X, base + i * lh, ln, hf, size, style) for i, ln in enumerate(lines)]
    if p.get("sub"):
        out.append(text(CARD_X, base + (len(lines) - 1) * lh + 100, p["sub"], sf, 50, anchor="start", fill=c["muted"]))
    hy = GRID_BOTTOM - 110
    out += [avatar(CARD_X + 34, hy, 26, style),
            text(CARD_X + 86, hy + 12, style.get("handle", ""), ui, 34, anchor="start", fill=c["ink"])]
    return svg.document(W, H, defs(style), "".join(out))


# ---------------------------------------------------------------- the card scene


def card_scene(lt: float, dur: float, p: dict, style: dict) -> str:
    head, bottom = headline_card(lt, dur, p, style, p.get("_step", ""))
    vis = p.get("visual")
    body = ""
    if vis and vis.get("type") in VISUALS:
        body = VISUALS[vis["type"]](lt, dur, vis, style, bottom + 10)
    return head + body


from . import story  # noqa: E402  (story uses this module's text helpers)

SCENES = {"card": card_scene, "endcard": endcard_scene, "story": story.story_scene}
