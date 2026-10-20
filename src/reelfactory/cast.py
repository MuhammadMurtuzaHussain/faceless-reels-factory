"""Characters and props for story scenes.

Two kinds of character, both drawn from primitives so they stay crisp and cheap:

* ``person``: a friendly "bean" (pawn body, round head, stubby arms) with a face that
  carries the emotion: eyes that blink and look around, brows and a mouth per mood.
* ``bot``: an AI agent: rounded screen-head with glowing eyes, antenna, hovering body.

Characters are anchored at their feet ``(x, y)``; ``size`` 1.0 is about 325 px tall for a
person and 240 px for a bot. Arms are posed with two angles per arm (see POSES).

Props are small illustrated objects (``PROPS``). Grounded props are anchored at their
bottom centre, floating props at their centre (``GROUNDED`` lists which is which).
"""
from __future__ import annotations

import math
from xml.sax.saxutils import escape

from . import svg
from .svg import circle, clamp, ease_in_out_cubic, ease_out_back, ease_out_cubic, group, lerp, line, path, progress, \
    rect, scale_about, text

INK = "#1a1d27"
CREAM = "#fff6ea"

# ---------------------------------------------------------------- colour + maths helpers


def _rgb(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def mix(a: str, b: str, t: float) -> str:
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    t = clamp(t)
    return "#{:02x}{:02x}{:02x}".format(round(lerp(ra, rb, t)), round(lerp(ga, gb, t)), round(lerp(ba, bb, t)))


def tint(c: str, k: float) -> str:
    return mix(c, "#ffffff", k)


def shade(c: str, k: float) -> str:
    return mix(c, "#000000", k)


def _safe_id(key: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in key)


def hash01(s: str, k: int = 0) -> float:
    """Deterministic pseudo-random 0..1 for a string (so every frame agrees)."""
    h = 2166136261
    for ch in f"{s}:{k}":
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return (h % 10007) / 10007


def deg_dir(a: float, sgn: int) -> tuple[float, float]:
    """Unit vector for an arm angle: 0 = straight down, 90 = out to the side, 180 = up (sgn: -1 left, +1 right)."""
    r = math.radians(a)
    return sgn * math.sin(r), math.cos(r)


def ease_out_bounce(p: float) -> float:
    p = clamp(p)
    n, d = 7.5625, 2.75
    if p < 1 / d:
        return n * p * p
    if p < 2 / d:
        p -= 1.5 / d
        return n * p * p + 0.75
    if p < 2.5 / d:
        p -= 2.25 / d
        return n * p * p + 0.9375
    p -= 2.625 / d
    return n * p * p + 0.984375


def grad_lr(gid: str, color: str, light: float = 0.18, dark: float = 0.22) -> str:
    """Inline left-lit gradient for a body (objectBoundingBox units)."""
    return (f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0.25">'
            f'<stop offset="0" stop-color="{tint(color, light)}"/><stop offset="0.55" stop-color="{color}"/>'
            f'<stop offset="1" stop-color="{shade(color, dark)}"/></linearGradient></defs>')


def grad_radial(gid: str, color: str, light: float = 0.25, dark: float = 0.18) -> str:
    return (f'<defs><radialGradient id="{gid}" cx="0.35" cy="0.3" r="0.8">'
            f'<stop offset="0" stop-color="{tint(color, light)}"/><stop offset="0.6" stop-color="{color}"/>'
            f'<stop offset="1" stop-color="{shade(color, dark)}"/></radialGradient></defs>')


def ui_font(style: dict) -> dict:
    return style["fonts"]["ui"]


def title_font(style: dict) -> dict:
    return style["fonts"].get("title") or style["fonts"]["ui"]


# ---------------------------------------------------------------- poses
# (shoulder angle, forearm bend) for the screen-left arm and the screen-right arm, in degrees.
# 0 = hanging down, 90 = straight out, 180 = straight up; negative angles swing across the body.

POSES: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "idle": ((14, 10), (14, 10)),
    "wave": ((14, 10), (145, 25)),
    "cheer": ((152, 12), (152, 12)),
    "point": ((14, 10), (96, -6)),
    "present": ((14, 10), (62, -30)),
    "type": ((-22, -52), (-22, -52)),
    "hold": ((14, 10), (-12, -80)),
    "think": ((-28, -62), (-6, -146)),
    "shrug": ((58, 92), (58, 92)),
    "relax": ((160, 150), (160, 150)),
    "panic": ((128, 36), (128, 36)),
    "cross": ((-38, -96), (-38, -96)),
    "juggle": ((38, 62), (38, 62)),
    "throw": ((14, 10), (168, 8)),
    "catch": ((118, 30), (118, 30)),
    "hips": ((35, -120), (35, -120)),
    "sad": ((4, 2), (4, 2)),
}


def pose_angles(name: str) -> tuple[tuple[float, float], tuple[float, float]]:
    """Look up a pose; ``<pose>-left`` mirrors it (e.g. point-left)."""
    if name.endswith("-left"):
        l, r = POSES.get(name[:-5], POSES["idle"])
        return r, l
    return POSES.get(name, POSES["idle"])


def live_angles(pose: str, lt: float, seed: float) -> tuple[list[float], list[float]]:
    """Pose angles plus the small loops that make a pose feel alive (typing, waving, panicking)."""
    (ls, le), (rs, re) = pose_angles(pose)
    L, R = [ls, le], [rs, re]
    base = pose[:-5] if pose.endswith("-left") else pose
    if base == "wave":
        k = math.sin(lt * 2 * math.pi * 2.2) * 26
        (L if pose.endswith("-left") else R)[1] += k
    elif base == "type":
        L[1] += math.sin(lt * 2 * math.pi * 5.0) * 9
        R[1] += math.sin(lt * 2 * math.pi * 5.0 + 2.1) * 9
    elif base == "panic":
        L[0] += math.sin(lt * 2 * math.pi * 3.1) * 14
        R[0] += math.sin(lt * 2 * math.pi * 3.1 + 1.6) * 14
    elif base == "cheer":
        L[0] += math.sin(lt * 2 * math.pi * 1.6) * 8
        R[0] += math.sin(lt * 2 * math.pi * 1.6 + 0.6) * 8
    elif base == "juggle":
        L[1] += math.sin(lt * 2 * math.pi * 2.4) * 16
        R[1] += math.sin(lt * 2 * math.pi * 2.4 + math.pi) * 16
    elif base in ("idle", "hold", "present"):
        L[0] += math.sin(lt * 1.3 + seed * 6) * 3
        R[0] += math.sin(lt * 1.2 + seed * 6 + 1) * 3
    return L, R


def blend_angles(a: list[float], b: list[float], t: float) -> list[float]:
    return [lerp(x, y, t) for x, y in zip(a, b)]


def arm(sx: float, sy: float, sgn: int, ang: list[float], upper: float, fore: float, width: float,
        color: str, hand: str) -> tuple[str, tuple[float, float]]:
    dx, dy = deg_dir(ang[0], sgn)
    ex, ey = sx + dx * upper, sy + dy * upper
    fx, fy = deg_dir(ang[0] + ang[1], sgn)
    hx, hy = ex + fx * fore, ey + fy * fore
    d = f"M{sx:.1f} {sy:.1f}L{ex:.1f} {ey:.1f}L{hx:.1f} {hy:.1f}"
    out = path(d, fill="none", stroke=color, stroke_width=width, stroke_linecap="round", stroke_linejoin="round")
    out += circle(hx, hy, width * 0.62, fill=hand)
    return out, (hx, hy)


# ---------------------------------------------------------------- faces

MOODS = ("neutral", "happy", "grin", "smirk", "sly", "shock", "sad", "worried", "focused", "sleepy",
         "proud", "curious", "angry", "love")


def face(cx: float, cy: float, R: float, mood: str, look: tuple[float, float], blink: float, lt: float) -> str:
    """Eyes, brows and mouth on a head of radius R centred at (cx, cy)."""
    lx, ly = look
    cx += lx * R * 0.16
    cy += ly * R * 0.1
    out = []
    ex, ey = R * 0.32, -R * 0.06
    rx, ry = R * 0.095, R * 0.135
    if mood == "shock":
        rx, ry = R * 0.12, R * 0.17
    closed = mood in ("sleepy", "proud") or blink > 0.5
    for s in (-1, 1):
        x, y = cx + s * ex, cy + ey
        if closed:
            if mood == "proud":                    # happy closed eyes: ^ ^
                out.append(path(f"M{x - rx * 1.3:.1f} {y + ry * 0.4:.1f}Q{x:.1f} {y - ry * 1.1:.1f} {x + rx * 1.3:.1f} {y + ry * 0.4:.1f}",
                                fill="none", stroke=INK, stroke_width=R * 0.06, stroke_linecap="round"))
            else:
                out.append(path(f"M{x - rx * 1.2:.1f} {y:.1f}Q{x:.1f} {y + ry * 0.7:.1f} {x + rx * 1.2:.1f} {y:.1f}",
                                fill="none", stroke=INK, stroke_width=R * 0.055, stroke_linecap="round"))
            continue
        out.append(f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="{INK}"/>')
        out.append(circle(x - rx * 0.3 + lx * rx * 0.2, y - ry * 0.38, rx * 0.36, fill="#ffffff", opacity=0.9))
        if mood == "love":
            out.append(_heart(x, y - ry * 0.1, rx * 1.1, "#ff5d7a"))
    # brows: (inner y offset, outer y offset) in units of R, negative = up
    brows = {"happy": (-0.36, -0.38), "grin": (-0.37, -0.39), "shock": (-0.47, -0.45), "sad": (-0.4, -0.3),
             "worried": (-0.42, -0.31), "focused": (-0.28, -0.35), "angry": (-0.24, -0.4), "sly": (-0.27, -0.36),
             "smirk": (-0.33, -0.37), "curious": (-0.33, -0.33), "sleepy": (-0.3, -0.3), "proud": (-0.38, -0.38)}
    bi, bo = brows.get(mood, (-0.34, -0.34))
    for s in (-1, 1):
        x = cx + s * ex
        inner, outer = (x - s * R * 0.12, cy + bi * R), (x + s * R * 0.13, cy + bo * R)
        if mood == "curious" and s == 1:
            inner, outer = (inner[0], inner[1] - R * 0.1), (outer[0], outer[1] - R * 0.12)
        out.append(line(inner[0], inner[1], outer[0], outer[1], stroke=INK, stroke_width=R * 0.06,
                        stroke_linecap="round", opacity=0.85))
    my = cy + R * 0.36
    mw = R * 0.2
    sw = R * 0.06
    k = dict(fill="none", stroke=INK, stroke_width=sw, stroke_linecap="round", stroke_linejoin="round")
    if mood in ("happy", "proud", "love"):
        out.append(path(f"M{cx - mw:.1f} {my - R * 0.03:.1f}Q{cx:.1f} {my + R * 0.16:.1f} {cx + mw:.1f} {my - R * 0.03:.1f}", **k))
    elif mood == "grin":
        out.append(path(f"M{cx - mw * 1.15:.1f} {my - R * 0.06:.1f}H{cx + mw * 1.15:.1f}Q{cx + mw:.1f} {my + R * 0.22:.1f} "
                        f"{cx:.1f} {my + R * 0.22:.1f}Q{cx - mw:.1f} {my + R * 0.22:.1f} {cx - mw * 1.15:.1f} {my - R * 0.06:.1f}Z",
                        fill=INK))
        out.append(f'<ellipse cx="{cx:.1f}" cy="{my + R * 0.13:.1f}" rx="{mw * 0.55:.1f}" ry="{R * 0.06:.1f}" fill="#ff8a8a"/>')
    elif mood in ("smirk", "sly"):
        out.append(path(f"M{cx - mw:.1f} {my + R * 0.02:.1f}Q{cx + mw * 0.2:.1f} {my + R * 0.1:.1f} {cx + mw * 1.1:.1f} {my - R * 0.08:.1f}", **k))
    elif mood == "shock":
        o = 1 + 0.08 * math.sin(lt * 9)
        out.append(f'<ellipse cx="{cx:.1f}" cy="{my + R * 0.04:.1f}" rx="{R * 0.1 * o:.1f}" ry="{R * 0.13 * o:.1f}" fill="{INK}"/>')
    elif mood in ("sad", "angry"):
        out.append(path(f"M{cx - mw:.1f} {my + R * 0.08:.1f}Q{cx:.1f} {my - R * 0.08:.1f} {cx + mw:.1f} {my + R * 0.08:.1f}", **k))
    elif mood == "worried":
        out.append(path(f"M{cx - mw:.1f} {my + R * 0.03:.1f}q{mw * 0.5:.1f} {-R * 0.07:.1f} {mw:.1f} 0t{mw:.1f} 0", **k))
    elif mood == "sleepy":
        out.append(circle(cx, my + R * 0.03, R * 0.05, fill=INK))
    elif mood == "curious":
        out.append(circle(cx + R * 0.03, my + R * 0.02, R * 0.06, fill=INK))
    else:                                           # neutral / focused
        out.append(line(cx - mw * 0.75, my, cx + mw * 0.75, my, **k))
    if mood in ("happy", "grin", "proud", "love"):
        for s in (-1, 1):
            out.append(f'<ellipse cx="{cx + s * R * 0.5:.1f}" cy="{cy + R * 0.2:.1f}" rx="{R * 0.13:.1f}" ry="{R * 0.08:.1f}" '
                       f'fill="#ff7b8a" opacity="0.35"/>')
    return "".join(out)


def _heart(x: float, y: float, s: float, color: str) -> str:
    return path(f"M{x:.1f} {y + s * 0.55:.1f}C{x - s * 1.1:.1f} {y - s * 0.1:.1f} {x - s * 0.5:.1f} {y - s * 0.9:.1f} {x:.1f} {y - s * 0.3:.1f}"
                f"C{x + s * 0.5:.1f} {y - s * 0.9:.1f} {x + s * 1.1:.1f} {y - s * 0.1:.1f} {x:.1f} {y + s * 0.55:.1f}Z", fill=color)


def blink_at(lt: float, seed: float) -> float:
    """1 while the eyes are shut (a 0.12 s blink every ~3.4 s, offset per character)."""
    period = 3.1 + seed * 1.4
    ph = (lt + seed * 7) % period
    return 1.0 if ph < 0.12 else 0.0


# ---------------------------------------------------------------- people


def person(x: float, y: float, size: float, color: str, lt: float, *, key: str = "p", pose: str = "idle",
           prev_pose: str | None = None, pose_blend: float = 1.0, mood: str = "neutral",
           look: tuple[float, float] = (0, 0), outfit=(), walking: float = 0.0, hold: str | None = None,
           name: str | None = None, style: dict | None = None, tilt: float = 0.0) -> str:
    """A bean character standing at (x, y). ``walking`` > 0 adds a waddle; ``hold`` draws a prop in the right hand."""
    u = 100 * size
    seed = hash01(key)
    outfit = [outfit] if isinstance(outfit, str) else list(outfit or [])
    bw, tw, bh = 1.62 * u, 1.28 * u, 1.9 * u
    R = 0.74 * u
    breath = math.sin(lt * 2 * math.pi * 0.42 + seed * 6) * 0.012
    hop = abs(math.sin(lt * 2 * math.pi * 2.3)) * 0.18 * u * walking
    sway = math.sin(lt * 2 * math.pi * 2.3) * 5 * walking + tilt
    body_col = color
    if "labcoat" in outfit:
        body_col = "#f4f1ea"
    elif "hoodie" in outfit:
        body_col = shade(color, 0.12)
    elif "suit" in outfit:
        body_col = "#3a4256"
    head_col = mix("#f7ecdf", color, 0.14) if "skin" not in outfit else "#f2c9a5"
    gid = "pb" + _safe_id(key)
    out = [f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{bw * 0.62:.1f}" ry="{u * 0.13:.1f}" fill="#000" opacity="{0.32 - hop / u * 0.4:.2f}"/>']
    fig = [grad_lr(gid + "b", body_col), grad_radial(gid + "h", head_col)]
    by = y - hop
    r = 0.26 * u
    d = (f"M{x - bw / 2 + r:.1f} {by:.1f}H{x + bw / 2 - r:.1f}Q{x + bw / 2:.1f} {by:.1f} {x + bw / 2:.1f} {by - r:.1f}"
         f"C{x + bw / 2:.1f} {by - bh * 0.48:.1f} {x + tw / 2:.1f} {by - bh * 0.72:.1f} {x + tw / 2:.1f} {by - bh + tw * 0.42:.1f}"
         f"A{tw / 2:.1f} {tw * 0.42:.1f} 0 0 0 {x - tw / 2:.1f} {by - bh + tw * 0.42:.1f}"
         f"C{x - tw / 2:.1f} {by - bh * 0.72:.1f} {x - bw / 2:.1f} {by - bh * 0.48:.1f} {x - bw / 2:.1f} {by - r:.1f}"
         f"Q{x - bw / 2:.1f} {by:.1f} {x - bw / 2 + r:.1f} {by:.1f}Z")
    fig.append(path(d, fill=f"url(#{gid}b)"))
    # outfit details on the body
    if "labcoat" in outfit:
        fig.append(path(f"M{x:.1f} {by - bh + 0.2 * u:.1f}L{x:.1f} {by:.1f}", stroke="#d9d4ca", stroke_width=0.04 * u))
        fig.append(path(f"M{x - 0.42 * u:.1f} {by - bh + 0.12 * u:.1f}L{x:.1f} {by - bh + 0.55 * u:.1f}L{x + 0.42 * u:.1f} {by - bh + 0.12 * u:.1f}",
                        fill="none", stroke="#d9d4ca", stroke_width=0.05 * u, stroke_linejoin="round"))
        fig.append(rect(x + 0.22 * u, by - bh * 0.52, 0.32 * u, 0.26 * u, rx=0.05 * u, fill="none", stroke="#d9d4ca", stroke_width=0.035 * u))
        fig.append(line(x + 0.3 * u, by - bh * 0.56, x + 0.3 * u, by - bh * 0.44, stroke=color, stroke_width=0.05 * u, stroke_linecap="round"))
    if "hoodie" in outfit:
        fig.append(rect(x - 0.42 * u, by - bh * 0.42, 0.84 * u, 0.36 * u, rx=0.14 * u, fill=shade(color, 0.24)))
        for s in (-1, 1):
            fig.append(line(x + s * 0.18 * u, by - bh + 0.18 * u, x + s * 0.2 * u, by - bh + 0.6 * u, stroke=tint(color, 0.5),
                            stroke_width=0.04 * u, stroke_linecap="round"))
    if "tie" in outfit or "suit" in outfit:
        if "suit" in outfit:
            fig.append(path(f"M{x - 0.32 * u:.1f} {by - bh + 0.1 * u:.1f}L{x:.1f} {by - bh + 0.75 * u:.1f}L{x + 0.32 * u:.1f} {by - bh + 0.1 * u:.1f}Z",
                            fill="#f4f1ea"))
        fig.append(path(f"M{x:.1f} {by - bh + 0.18 * u:.1f}l{0.1 * u:.1f} {0.12 * u:.1f}l{-0.05 * u:.1f} {0.55 * u:.1f}"
                        f"l{-0.05 * u:.1f} {0.1 * u:.1f}l{-0.05 * u:.1f} {-0.1 * u:.1f}l{-0.05 * u:.1f} {-0.55 * u:.1f}Z",
                        fill=style["colors"]["accent"] if style else "#d97757"))
    if name:
        f_ = ui_font(style) if style else {"family": "Inter", "weight": 600}
        tw_ = svg.text_width(name, f_["file"], 0.2 * u) + 0.3 * u if style else len(name) * 0.12 * u + 0.3 * u
        fig.append(rect(x - tw_ / 2, by - bh * 0.62, tw_, 0.34 * u, rx=0.17 * u, fill="#ffffff", opacity=0.92))
        fig.append(text(x, by - bh * 0.62 + 0.24 * u, name, f_, 0.2 * u, fill=INK))
    # head
    hx, hy = x, by - bh - R * 0.72
    if "hoodie" in outfit:
        fig.append(circle(hx, hy + R * 0.05, R * 1.2, fill=shade(color, 0.16)))
    fig.append(circle(hx, hy, R, fill=f"url(#{gid}h)"))
    lk = look
    fig.append(face(hx, hy, R, mood, lk, blink_at(lt, seed), lt))
    if "hoodie" in outfit:   # hood rim over the forehead
        fig.append(path(f"M{hx - R * 1.12:.1f} {hy + R * 0.1:.1f}A{R * 1.16:.1f} {R * 1.16:.1f} 0 0 1 {hx + R * 1.12:.1f} {hy + R * 0.1:.1f}"
                        f"A{R * 1.02:.1f} {R * 0.92:.1f} 0 0 0 {hx - R * 1.12:.1f} {hy + R * 0.1:.1f}Z", fill=shade(color, 0.16)))
    if "glasses" in outfit:
        gx = hx + lk[0] * R * 0.16
        for s in (-1, 1):
            fig.append(circle(gx + s * R * 0.32, hy - R * 0.05, R * 0.23, fill="#ffffff", fill_opacity=0.12, stroke=INK,
                              stroke_width=R * 0.06))
        fig.append(line(gx - R * 0.1, hy - R * 0.07, gx + R * 0.1, hy - R * 0.07, stroke=INK, stroke_width=R * 0.06))
    if "cap" in outfit:
        cc = style["colors"]["accent"] if style else "#d97757"
        fig.append(path(f"M{hx - R * 0.95:.1f} {hy - R * 0.32:.1f}A{R * 0.97:.1f} {R * 0.95:.1f} 0 0 1 {hx + R * 0.95:.1f} {hy - R * 0.32:.1f}Z", fill=cc))
        fig.append(rect(hx - R * 0.2, hy - R * 0.42, R * 1.45, R * 0.18, rx=R * 0.09, fill=shade(cc, 0.15)))
    if "headset" in outfit:
        fig.append(path(f"M{hx - R * 0.98:.1f} {hy:.1f}A{R:.1f} {R * 1.05:.1f} 0 0 1 {hx + R * 0.98:.1f} {hy:.1f}", fill="none",
                        stroke="#2d3240", stroke_width=R * 0.12))
        for s in (-1, 1):
            fig.append(rect(hx + s * R * 0.98 - R * 0.15, hy - R * 0.2, R * 0.3, R * 0.42, rx=R * 0.12, fill="#2d3240"))
        fig.append(path(f"M{hx + R * 0.98:.1f} {hy + R * 0.15:.1f}Q{hx + R * 0.8:.1f} {hy + R * 0.6:.1f} {hx + R * 0.25:.1f} {hy + R * 0.55:.1f}",
                        fill="none", stroke="#2d3240", stroke_width=R * 0.07, stroke_linecap="round"))
    # arms (drawn last so hands can reach in front of the body and face)
    L, Rr = live_angles(pose, lt, seed)
    if prev_pose and pose_blend < 1:
        pL, pR = live_angles(prev_pose, lt, seed)
        e = ease_in_out_cubic(pose_blend)
        L, Rr = blend_angles(pL, L, e), blend_angles(pR, Rr, e)
    if walking:
        L[0] += math.sin(lt * 2 * math.pi * 2.3) * 18 * walking
        Rr[0] -= math.sin(lt * 2 * math.pi * 2.3) * 18 * walking
    shoulder_y = by - bh + 0.42 * u
    arm_col = shade(body_col, 0.08)
    hand_col = head_col
    hands = []
    for sgn, ang in ((-1, L), (1, Rr)):
        a, hpos = arm(x + sgn * tw * 0.4, shoulder_y, sgn, ang, 0.56 * u, 0.5 * u, 0.24 * u, arm_col, hand_col)
        fig.append(a)
        hands.append(hpos)
    if pose.startswith("juggle"):
        fig.append(juggle_balls(x, by - bh - 0.2 * u, u, lt))
    if hold:
        hxp, hyp = hands[1]
        fig.append(prop(hold, hxp + 0.12 * u, hyp - 0.1 * u, size * 0.55, {}, lt, style or {}))
    tr = f"rotate({sway:.2f} {x:.1f} {y:.1f}) " + scale_about(x, y, 1)
    sq = f"translate({x:.1f} {y:.1f}) scale({1 - breath * 0.6:.4f} {1 + breath:.4f}) translate({-x:.1f} {-y:.1f})"
    out.append(group(fig, transform=f"{tr} {sq}"))
    return "".join(out)


def juggle_balls(cx: float, cy: float, u: float, lt: float, n: int = 3) -> str:
    cols = ["#ff8a3d", "#6c8cff", "#6fcf97", "#f2c14e"]
    out = []
    for i in range(n):
        ph = (lt * 1.15 + i / n) % 1.0
        a = ph * 2 * math.pi
        bx = cx + math.cos(a) * 0.62 * u
        byy = cy - 0.6 * u - abs(math.sin(a)) * 0.9 * u
        out.append(circle(bx, byy, 0.15 * u, fill=cols[i % len(cols)]))
        out.append(circle(bx - 0.05 * u, byy - 0.05 * u, 0.05 * u, fill="#ffffff", opacity=0.6))
    return "".join(out)


# ---------------------------------------------------------------- bots (AI agents)


def bot(x: float, y: float, size: float, color: str, lt: float, *, key: str = "b", pose: str = "idle",
        prev_pose: str | None = None, pose_blend: float = 1.0, mood: str = "neutral",
        look: tuple[float, float] = (0, 0), walking: float = 0.0, hold: str | None = None, name: str | None = None,
        style: dict | None = None, eye: str = "#ffe9d2", tilt: float = 0.0, outfit=()) -> str:
    """A hovering agent robot whose feet-point is (x, y)."""
    u = 100 * size
    seed = hash01(key)
    hover = math.sin(lt * 2 * math.pi * 0.8 + seed * 6) * 0.07 * u + 0.28 * u + abs(math.sin(lt * 2 * math.pi * 2.3)) * 0.12 * u * walking
    sway = math.sin(lt * 2 * math.pi * 0.6 + seed * 3) * 2.5 + tilt + math.sin(lt * 2 * math.pi * 2.3) * 4 * walking
    by = y - hover
    gid = "bb" + _safe_id(key)
    out = [f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{0.72 * u:.1f}" ry="{0.11 * u:.1f}" fill="#000" opacity="0.28"/>',
           f'<ellipse cx="{x:.1f}" cy="{by + 0.02 * u:.1f}" rx="{0.42 * u:.1f}" ry="{0.2 * u:.1f}" fill="url(#g-warm)" opacity="{0.55 + 0.25 * math.sin(lt * 17):.2f}"/>']
    fig = [grad_lr(gid + "b", color, 0.25, 0.25), grad_lr(gid + "h", tint(color, 0.08), 0.3, 0.25)]
    # body capsule
    fig.append(rect(x - 0.5 * u, by - 0.95 * u, 1.0 * u, 0.85 * u, rx=0.42 * u, fill=f"url(#{gid}b)"))
    fig.append(circle(x, by - 0.55 * u, 0.13 * u, fill=tint(eye, 0.2), opacity=0.55 + 0.35 * math.sin(lt * 3 + seed * 5)))
    # arms
    L, Rr = live_angles(pose, lt, seed)
    if prev_pose and pose_blend < 1:
        pL, pR = live_angles(prev_pose, lt, seed)
        e = ease_in_out_cubic(pose_blend)
        L, Rr = blend_angles(pL, L, e), blend_angles(pR, Rr, e)
    hands = []
    for sgn, ang in ((-1, L), (1, Rr)):
        a, hp = arm(x + sgn * 0.46 * u, by - 0.78 * u, sgn, ang, 0.34 * u, 0.3 * u, 0.15 * u, shade(color, 0.12), tint(color, 0.3))
        fig.append(a)
        hands.append(hp)
    # head
    hx, hy = x, by - 1.62 * u
    fig.append(line(hx, hy - 0.58 * u, hx, hy - 0.86 * u, stroke=shade(color, 0.2), stroke_width=0.07 * u, stroke_linecap="round"))
    bulb = 0.5 + 0.5 * math.sin(lt * 2 * math.pi * 1.1 + seed * 4)
    fig.append(circle(hx, hy - 0.9 * u, 0.2 * u, fill="url(#g-warm)", opacity=0.4 + 0.5 * bulb))
    fig.append(circle(hx, hy - 0.9 * u, 0.09 * u, fill=tint(eye, 0.1)))
    for s in (-1, 1):
        fig.append(rect(hx + s * 0.8 * u - 0.1 * u, hy - 0.2 * u, 0.2 * u, 0.4 * u, rx=0.1 * u, fill=shade(color, 0.2)))
    fig.append(rect(hx - 0.78 * u, hy - 0.58 * u, 1.56 * u, 1.16 * u, rx=0.38 * u, fill=f"url(#{gid}h)"))
    fig.append(rect(hx - 0.62 * u, hy - 0.42 * u, 1.24 * u, 0.82 * u, rx=0.26 * u, fill="#151925"))
    fig.append(rect(hx - 0.56 * u, hy - 0.38 * u, 0.5 * u, 0.16 * u, rx=0.08 * u, fill="#ffffff", opacity=0.07))
    fig.append(bot_eyes(hx + look[0] * 0.12 * u, hy + look[1] * 0.06 * u, u, mood, eye, blink_at(lt, seed), lt))
    if "cap" in (outfit or ()):
        cc = style["colors"]["accent"] if style else "#d97757"
        fig.append(path(f"M{hx - 0.7 * u:.1f} {hy - 0.5 * u:.1f}Q{hx:.1f} {hy - 1.0 * u:.1f} {hx + 0.7 * u:.1f} {hy - 0.5 * u:.1f}Z", fill=cc))
    if pose.startswith("juggle"):
        fig.append(juggle_balls(x, hy - 0.2 * u, u * 0.9, lt))
    if hold:
        hxp, hyp = hands[1]
        fig.append(prop(hold, hxp + 0.1 * u, hyp - 0.1 * u, size * 0.6, {}, lt, style or {}))
    if name:
        f_ = ui_font(style) if style else {"family": "Inter", "weight": 600, "file": "Inter-SemiBold.ttf"}
        fs = max(0.24 * u, 22)
        tw_ = (svg.text_width(name, f_["file"], fs) if style else len(name) * fs * 0.55) + fs * 1.1
        fig.append(rect(x - tw_ / 2, y + 0.18 * u, tw_, fs * 1.55, rx=fs * 0.77, fill="#ffffff", opacity=0.94))
        fig.append(text(x, y + 0.18 * u + fs * 1.1, name, f_, fs, fill=INK))
    out.append(group(fig, transform=f"rotate({sway:.2f} {x:.1f} {by:.1f})"))
    return "".join(out)


def bot_eyes(cx: float, cy: float, u: float, mood: str, col: str, blink: float, lt: float) -> str:
    out = [f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{0.55 * u:.1f}" ry="{0.32 * u:.1f}" fill="url(#g-warm)" opacity="0.22"/>']
    k = dict(fill="none", stroke=col, stroke_width=0.09 * u, stroke_linecap="round", stroke_linejoin="round")
    for s in (-1, 1):
        x = cx + s * 0.28 * u
        if mood in ("happy", "proud", "grin", "love"):
            out.append(path(f"M{x - 0.12 * u:.1f} {cy + 0.06 * u:.1f}Q{x:.1f} {cy - 0.16 * u:.1f} {x + 0.12 * u:.1f} {cy + 0.06 * u:.1f}", **k))
        elif mood in ("sleepy",) or blink > 0.5:
            out.append(line(x - 0.12 * u, cy, x + 0.12 * u, cy, **k))
        elif mood in ("sad", "worried"):
            out.append(path(f"M{x - 0.12 * u:.1f} {cy - 0.04 * u:.1f}Q{x:.1f} {cy + 0.14 * u:.1f} {x + 0.12 * u:.1f} {cy - 0.04 * u:.1f}", **k))
            if mood == "worried":
                out.append(line(x - s * 0.1 * u, cy - 0.2 * u, x + s * 0.12 * u, cy - 0.14 * u, **{**k, "stroke_width": 0.06 * u}))
        elif mood in ("angry", "focused", "sly"):
            out.append(rect(x - 0.12 * u, cy - 0.06 * u, 0.24 * u, 0.13 * u, rx=0.06 * u, fill=col))
            out.append(line(x - s * 0.15 * u, cy - 0.22 * u, x + s * 0.14 * u, cy - 0.13 * u, **{**k, "stroke_width": 0.06 * u}))
        elif mood == "shock":
            out.append(circle(x, cy, 0.14 * u, fill="none", stroke=col, stroke_width=0.07 * u))
        elif mood == "curious":
            r = 0.13 * u if s == 1 else 0.09 * u
            out.append(rect(x - r * 0.75, cy - r, r * 1.5, r * 2, rx=r * 0.75, fill=col))
        else:
            out.append(rect(x - 0.09 * u, cy - 0.13 * u, 0.18 * u, 0.26 * u, rx=0.09 * u, fill=col))
    if mood == "shock":
        out.append(circle(cx, cy + 0.2 * u, 0.05 * u, fill=col))
    elif mood in ("happy", "grin", "proud"):
        out.append(path(f"M{cx - 0.1 * u:.1f} {cy + 0.18 * u:.1f}Q{cx:.1f} {cy + 0.26 * u:.1f} {cx + 0.1 * u:.1f} {cy + 0.18 * u:.1f}", **{**k, "stroke_width": 0.05 * u}))
    return "".join(out)


# ---------------------------------------------------------------- emotes + speech bubbles


def emote(kind: str, x: float, y: float, s: float, e: float, lt: float, style: dict) -> str:
    """A small reaction icon popping above a head; ``e`` is its 0..1 entrance."""
    c = style["colors"]
    sc = ease_out_back(e)
    if sc <= 0.01:
        return ""
    wob = math.sin(lt * 6) * 4
    f = title_font(style)
    if kind in ("!", "!!", "?"):
        col = c.get("danger", "#ff4d5e") if kind != "?" else c["slate"]
        body = [circle(x, y, 44 * s, fill=col), text(x, y + 17 * s, kind, f, 52 * s, fill="#ffffff")]
    elif kind == "sparkle":
        body = [_sparkle(x + dx * s, y + dy * s, r * s, c["mustard"], lt + i) for i, (dx, dy, r) in
                enumerate(((0, 0, 30), (-44, 26, 16), (40, -30, 18)))]
    elif kind == "heart":
        body = [_heart(x, y, 34 * s, "#ff5d7a")]
    elif kind == "zzz":
        body = [text(x + i * 26 * s, y - i * 30 * s, "z", f, (34 + i * 10) * s, fill=c["ink"], opacity=0.8) for i in range(3)]
    elif kind == "sweat":
        body = [path(f"M{x:.1f} {y - 26 * s:.1f}Q{x + 20 * s:.1f} {y + 4 * s:.1f} {x:.1f} {y + 14 * s:.1f}Q{x - 20 * s:.1f} {y + 4 * s:.1f} {x:.1f} {y - 26 * s:.1f}Z",
                     fill="#7cc6ff")]
    elif kind == "idea":
        body = [prop("bulb", x, y, 0.55 * s, {"state": "on"}, lt, style)]
    elif kind in ("check", "cross"):
        col = c["sage"] if kind == "check" else c.get("danger", "#ff4d5e")
        mark = (f"M{x - 18 * s:.1f} {y:.1f}l{12 * s:.1f} {13 * s:.1f}l{24 * s:.1f} {-26 * s:.1f}" if kind == "check" else
                f"M{x - 15 * s:.1f} {y - 15 * s:.1f}l{30 * s:.1f} {30 * s:.1f}M{x + 15 * s:.1f} {y - 15 * s:.1f}l{-30 * s:.1f} {30 * s:.1f}")
        body = [circle(x, y, 42 * s, fill=col), path(mark, fill="none", stroke="#fff", stroke_width=9 * s, stroke_linecap="round",
                                                     stroke_linejoin="round")]
    elif kind == "music":
        body = [text(x, y + 18 * s, "♪", f, 70 * s, fill=c["mustard"])]
    else:
        body = [text(x, y + 18 * s, kind[:3], f, 50 * s, fill=c["ink"])]
    return group(body, transform=f"translate(0 {-(1 - e) * 30:.1f}) rotate({wob:.1f} {x:.1f} {y:.1f}) {scale_about(x, y, sc)}")


def _sparkle(x: float, y: float, r: float, col: str, ph: float) -> str:
    k = 0.8 + 0.2 * math.sin(ph * 5)
    r *= k
    return path(f"M{x:.1f} {y - r:.1f}Q{x + r * 0.18:.1f} {y - r * 0.18:.1f} {x + r:.1f} {y:.1f}Q{x + r * 0.18:.1f} {y + r * 0.18:.1f} {x:.1f} {y + r:.1f}"
                f"Q{x - r * 0.18:.1f} {y + r * 0.18:.1f} {x - r:.1f} {y:.1f}Q{x - r * 0.18:.1f} {y - r * 0.18:.1f} {x:.1f} {y - r:.1f}Z", fill=col)


def bubble(txt: str, x: float, y: float, e: float, style: dict, side: int = 1) -> str:
    """Speech bubble whose tail points at (x, y); ``side`` +1 grows to the right, -1 to the left."""
    if e <= 0.01:
        return ""
    f = style["fonts"]["ui"]
    size = 38
    words = txt.split()
    lines_, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if cur and svg.text_width(trial, f["file"], size) > 420:
            lines_.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines_.append(cur)
    tw = max(svg.text_width(l_, f["file"], size) for l_ in lines_)
    bw, bh = tw + 56, len(lines_) * size * 1.25 + 34
    bx = x + (20 if side > 0 else -bw - 20)
    bx = clamp(bx, 40, 1040 - bw)
    by = y - bh - 34
    tail_x = clamp(x + side * 34, bx + 30, bx + bw - 30)
    out = [rect(bx, by, bw, bh, rx=min(34, bh / 2), fill="#ffffff"),
           path(f"M{tail_x - 18:.1f} {by + bh - 2:.1f}L{x:.1f} {y:.1f}L{tail_x + 18:.1f} {by + bh - 2:.1f}Z", fill="#ffffff")]
    for i, l_ in enumerate(lines_):
        out.append(text(bx + bw / 2, by + 17 + size * 0.95 + i * size * 1.25, l_, f, size, fill=INK))
    sc = ease_out_back(e)
    return group(out, transform=scale_about(x, y, sc), opacity=min(1, e * 3))


# ---------------------------------------------------------------- props

GROUNDED = {"palm", "desk", "hoop", "building", "server", "mountain", "sign", "flag", "lamp", "block", "tower",
            "lava", "plant", "rock", "podium"}


def prop(kind: str, x: float, y: float, s: float, st: dict, lt: float, style: dict) -> str:
    fn = PROPS.get(kind)
    if fn is None:
        return circle(x, y, 30 * s, fill=style.get("colors", {}).get("muted", "#888"))
    return fn(x, y, s, st, lt, style)


def _c(style: dict, k: str, d: str) -> str:
    return (style.get("colors") or {}).get(k, d)


def p_palm(x, y, s, st, lt, style):
    u = 100 * s
    sway = math.sin(lt * 1.3) * 3
    trunk = (f"M{x - 0.14 * u:.1f} {y:.1f}C{x - 0.1 * u:.1f} {y - 1.4 * u:.1f} {x + 0.2 * u:.1f} {y - 2.4 * u:.1f} {x + 0.55 * u:.1f} {y - 3.1 * u:.1f}"
             f"L{x + 0.72 * u:.1f} {y - 3.0 * u:.1f}C{x + 0.4 * u:.1f} {y - 2.3 * u:.1f} {x + 0.16 * u:.1f} {y - 1.3 * u:.1f} {x + 0.16 * u:.1f} {y:.1f}Z")
    out = [path(trunk, fill="#8a5a3c")]
    for i in range(7):
        out.append(line(x - 0.1 * u + i * 0.03 * u + i * 0.06 * u, y - i * 0.42 * u, x + 0.15 * u + i * 0.08 * u, y - i * 0.42 * u - 0.05 * u,
                        stroke="#6d4630", stroke_width=0.05 * u, stroke_linecap="round"))
    tx, ty = x + 0.62 * u, y - 3.08 * u
    leaves = []
    for k, (ang, ln) in enumerate(((-160, 1.5), (-120, 1.3), (-60, 1.35), (-20, 1.5), (20, 1.2), (160, 1.2), (200, 1.1))):
        a = math.radians(ang + math.sin(lt * 1.6 + k) * 4)
        ex, ey = tx + math.cos(a) * ln * u, ty + math.sin(a) * ln * u * 0.75 + 0.35 * u
        mx, my = tx + math.cos(a) * ln * u * 0.5, ty + math.sin(a) * ln * u * 0.5 - 0.35 * u
        col = "#3f9a6b" if k % 2 else "#2f7f58"
        leaves.append(path(f"M{tx:.1f} {ty:.1f}Q{mx:.1f} {my - 0.25 * u:.1f} {ex:.1f} {ey:.1f}Q{mx:.1f} {my + 0.2 * u:.1f} {tx:.1f} {ty:.1f}Z", fill=col))
    for i in range(3):
        leaves.append(circle(tx - 0.12 * u + i * 0.14 * u, ty + 0.12 * u, 0.12 * u, fill="#6b4a2d"))
    out.append(group(leaves, transform=f"rotate({sway:.2f} {x:.1f} {y:.1f})"))
    return group(out)


def p_block(x, y, s, st, lt, style):
    u = 100 * s
    col = st.get("color") or _c(style, "sand", "#e8d7bf")
    w = 0.9 * u
    out = [rect(x - w / 2, y - w, w, w, rx=0.12 * u, fill=shade(col, 0.12)),
           rect(x - w / 2, y - w, w, w * 0.28, rx=0.12 * u, fill=tint(col, 0.2)),
           rect(x - w / 2 + 0.1 * u, y - w + 0.36 * u, w - 0.2 * u, 0.06 * u, rx=0.03 * u, fill=shade(col, 0.22), opacity=0.6)]
    return "".join(out)


def p_ball(x, y, s, st, lt, style):
    u = 100 * s
    r = 0.42 * u
    col = st.get("color") or "#ff8a3d"
    rot = st.get("spin", lt * 240)
    seams = [circle(x, y, r, fill=col), circle(x - r * 0.3, y - r * 0.35, r * 0.25, fill="#ffffff", opacity=0.25)]
    g = [line(x - r, y, x + r, y, stroke=shade(col, 0.45), stroke_width=0.05 * u),
         line(x, y - r, x, y + r, stroke=shade(col, 0.45), stroke_width=0.05 * u),
         path(f"M{x - r * 0.7:.1f} {y - r * 0.7:.1f}Q{x - r * 0.15:.1f} {y:.1f} {x - r * 0.7:.1f} {y + r * 0.7:.1f}", fill="none",
              stroke=shade(col, 0.45), stroke_width=0.05 * u),
         path(f"M{x + r * 0.7:.1f} {y - r * 0.7:.1f}Q{x + r * 0.15:.1f} {y:.1f} {x + r * 0.7:.1f} {y + r * 0.7:.1f}", fill="none",
              stroke=shade(col, 0.45), stroke_width=0.05 * u)]
    return "".join(seams) + group(g, transform=f"rotate({rot:.1f} {x:.1f} {y:.1f})")


def p_hoop(x, y, s, st, lt, style):
    u = 100 * s
    out = [rect(x - 0.08 * u, y - 3.4 * u, 0.16 * u, 3.4 * u, rx=0.06 * u, fill="#9aa3b5"),
           rect(x - 0.8 * u, y - 4.2 * u, 1.6 * u, 1.05 * u, rx=0.1 * u, fill="#f4f1ea", stroke="#c9ced8", stroke_width=0.05 * u),
           rect(x - 0.32 * u, y - 3.88 * u, 0.64 * u, 0.5 * u, rx=0.04 * u, fill="none", stroke="#ff7a59", stroke_width=0.06 * u)]
    rim_y = y - 3.25 * u
    net = []
    for i in range(6):
        t0 = -0.45 + i * 0.18
        net.append(line(x + t0 * u, rim_y, x + t0 * 0.6 * u, rim_y + 0.55 * u, stroke="#ffffff", stroke_width=0.03 * u, opacity=0.8))
    swish = st.get("swish", 0.0)
    out.append(group(net, transform=f"translate(0 {math.sin(swish * math.pi) * 0.1 * u:.1f})"))
    out.append(f'<ellipse cx="{x:.1f}" cy="{rim_y:.1f}" rx="{0.48 * u:.1f}" ry="{0.1 * u:.1f}" fill="none" stroke="#ff7a59" stroke_width="{0.07 * u:.1f}"/>'
               .replace("stroke_width", "stroke-width"))
    return "".join(out)


def p_clock(x, y, s, st, lt, style):
    u = 100 * s
    r = 0.95 * u
    c = style.get("colors", {})
    speed = st.get("speed", 1.0)
    out = [circle(x, y + 0.08 * u, r * 1.04, fill="#000", opacity=0.25),
           circle(x, y, r, fill="#f4f1ea", stroke=c.get("ink", "#fff"), stroke_width=0.08 * u)]
    for i in range(12):
        a = i / 12 * 2 * math.pi
        out.append(line(x + math.sin(a) * r * 0.78, y - math.cos(a) * r * 0.78, x + math.sin(a) * r * 0.88, y - math.cos(a) * r * 0.88,
                        stroke=INK, stroke_width=0.05 * u, stroke_linecap="round"))
    hm = lt * 360 * speed
    hh = hm / 12
    for ang, ln, w, col in ((hh, 0.45, 0.09, INK), (hm, 0.7, 0.06, c.get("accent", "#d97757"))):
        a = math.radians(ang)
        out.append(line(x, y, x + math.sin(a) * r * ln, y - math.cos(a) * r * ln, stroke=col, stroke_width=w * u, stroke_linecap="round"))
    out.append(circle(x, y, 0.08 * u, fill=INK))
    if st.get("label"):
        f = title_font(style)
        out.append(text(x, y + r + 0.75 * u, st["label"], f, 0.62 * u, fill=c.get("ink", "#fff")))
    return "".join(out)


def p_note(x, y, s, st, lt, style):
    """A sheet of paper: optional title, text lines, one highlighted line (``mark``) swiped on at ``mark_t``."""
    u = 100 * s
    f, fb = style["fonts"]["body"], style["fonts"]["ui"]
    lines_ = st.get("lines") or []
    w = st.get("w", 5.2) * u
    h = (1.1 + 0.62 * max(len(lines_), 3)) * u
    x0, y0 = x - w / 2, y - h / 2
    out = [rect(x0 + 0.1 * u, y0 + 0.16 * u, w, h, rx=0.18 * u, fill="#000", opacity=0.3),
           rect(x0, y0, w, h, rx=0.18 * u, fill="#fbf6ec")]
    if st.get("title"):
        out.append(text(x0 + 0.45 * u, y0 + 0.75 * u, st["title"], fb, 0.38 * u, anchor="start", fill=INK))
        out.append(line(x0 + 0.45 * u, y0 + 0.98 * u, x0 + w - 0.45 * u, y0 + 0.98 * u, stroke="#e3d9c8", stroke_width=0.03 * u))
    mark = st.get("mark")
    mk = st.get("mark_e", 1.0)
    for i, l_ in enumerate(lines_):
        ly = y0 + 1.6 * u + i * 0.62 * u
        if mark is not None and i == mark and mk > 0:
            tw = svg.text_width(l_, f["file"], 0.34 * u)
            out.append(rect(x0 + 0.38 * u, ly - 0.36 * u, (tw + 0.16 * u) * ease_out_cubic(mk), 0.5 * u, rx=0.08 * u,
                            fill=_c(style, "mustard", "#f2c14e"), opacity=0.85))
        out.append(text(x0 + 0.45 * u, ly, l_, f, 0.34 * u, anchor="start", fill="#3b3a40"))
    if not lines_:
        for i in range(4):
            ly = y0 + 1.5 * u + i * 0.5 * u
            out.append(rect(x0 + 0.45 * u, ly, (w - 0.9 * u) * (0.9 - 0.15 * (i % 2)), 0.14 * u, rx=0.07 * u, fill="#e3d9c8"))
    return "".join(out)


def p_window(x, y, s, st, lt, style):
    """An app/browser window with a title bar and either text lines or placeholder blocks."""
    u = 100 * s
    c = style.get("colors", {})
    w, h = st.get("w", 6.4) * u, st.get("h", 4.2) * u
    x0, y0 = x - w / 2, y - h / 2
    hacked = st.get("state") == "hacked"
    frame = c.get("danger", "#ff4d5e") if hacked else "#2a3142"
    out = [rect(x0 + 0.1 * u, y0 + 0.2 * u, w, h, rx=0.26 * u, fill="#000", opacity=0.35),
           rect(x0, y0, w, h, rx=0.26 * u, fill="#f6f3ee", stroke=frame, stroke_width=0.06 * u),
           path(f"M{x0:.1f} {y0 + 0.62 * u:.1f}V{y0 + 0.26 * u:.1f}Q{x0:.1f} {y0:.1f} {x0 + 0.26 * u:.1f} {y0:.1f}H{x0 + w - 0.26 * u:.1f}"
                f"Q{x0 + w:.1f} {y0:.1f} {x0 + w:.1f} {y0 + 0.26 * u:.1f}V{y0 + 0.62 * u:.1f}Z", fill=frame)]
    for i, col in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        out.append(circle(x0 + 0.38 * u + i * 0.3 * u, y0 + 0.31 * u, 0.09 * u, fill=col))
    if st.get("title"):
        out.append(text(x, y0 + 0.43 * u, st["title"], style["fonts"]["ui"], 0.28 * u, fill="#e9ecf3"))
    lines_ = st.get("lines")
    f = style["fonts"]["body"]
    if lines_:
        n_show = st.get("typed", len(lines_))
        for i, l_ in enumerate(lines_[: int(math.ceil(n_show))]):
            frac = clamp(n_show - i)
            shown = l_[: max(1, int(len(l_) * frac))] if frac < 1 else l_
            out.append(text(x0 + 0.4 * u, y0 + 1.25 * u + i * 0.55 * u, shown, f, 0.32 * u, anchor="start", fill="#2a2f3c"))
    else:
        out.append(rect(x0 + 0.4 * u, y0 + 0.95 * u, w * 0.45, 0.32 * u, rx=0.1 * u, fill=c.get("accent", "#d97757"), opacity=0.8))
        for i in range(3):
            out.append(rect(x0 + 0.4 * u, y0 + 1.55 * u + i * 0.45 * u, (w - 0.8 * u) * (0.95 - 0.2 * (i % 2)), 0.18 * u, rx=0.09 * u, fill="#ddd6cb"))
    if hacked:
        e = ease_out_back(st.get("state_e", 1))
        out.append(rect(x0, y0, w, h, rx=0.26 * u, fill=c.get("danger", "#ff4d5e"), opacity=0.18 + 0.08 * math.sin(lt * 12)))
        out.append(group([circle(x, y + 0.3 * u, 0.62 * u, fill=c.get("danger", "#ff4d5e")),
                          text(x, y + 0.55 * u, "!", title_font(style), 0.8 * u, fill="#fff")], transform=scale_about(x, y + 0.3 * u, e)))
    return "".join(out)


def p_terminal(x, y, s, st, lt, style):
    u = 100 * s
    w, h = st.get("w", 6.4) * u, st.get("h", 3.6) * u
    x0, y0 = x - w / 2, y - h / 2
    c = style.get("colors", {})
    out = [rect(x0 + 0.1 * u, y0 + 0.2 * u, w, h, rx=0.26 * u, fill="#000", opacity=0.4),
           rect(x0, y0, w, h, rx=0.26 * u, fill="#10131c", stroke="#2c3344", stroke_width=0.05 * u)]
    for i, col in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        out.append(circle(x0 + 0.38 * u + i * 0.3 * u, y0 + 0.34 * u, 0.09 * u, fill=col))
    if st.get("title"):
        out.append(text(x, y0 + 0.45 * u, st["title"], style["fonts"]["ui"], 0.28 * u, fill="#8e94a6"))
    f = style["fonts"]["body"]
    lines_ = st.get("lines") or []
    n_show = st.get("typed", len(lines_))
    last = None
    for i, l_ in enumerate(lines_[: int(math.ceil(n_show))]):
        frac = clamp(n_show - i)
        shown = l_[: max(1, int(len(l_) * frac))] if frac < 1 else l_
        ty = y0 + 1.1 * u + i * 0.55 * u
        out.append(text(x0 + 0.4 * u, ty, "> " + shown, f, 0.32 * u, anchor="start", fill=c.get("sage", "#6fcf97") if i % 2 == 0 else "#e9ecf3"))
        last = (x0 + 0.4 * u + svg.text_width("> " + shown, f["file"], 0.32 * u) + 0.06 * u, ty)
    if last and (lt * 2) % 1 < 0.6:
        out.append(rect(last[0], last[1] - 0.28 * u, 0.16 * u, 0.34 * u, fill="#e9ecf3"))
    return "".join(out)


def p_laptop(x, y, s, st, lt, style):
    """Laptop seen from the front, sitting with its base at (x, y)."""
    u = 100 * s
    on = st.get("state", "on") != "off"
    out = []
    if on:
        out.append(f'<ellipse cx="{x:.1f}" cy="{y - 0.9 * u:.1f}" rx="{1.9 * u:.1f}" ry="{1.4 * u:.1f}" fill="url(#g-cool)" opacity="0.5"/>')
    out += [rect(x - 1.1 * u, y - 1.55 * u, 2.2 * u, 1.45 * u, rx=0.12 * u, fill="#2b3040"),
            rect(x - 0.98 * u, y - 1.43 * u, 1.96 * u, 1.2 * u, rx=0.06 * u, fill="#7fb6ff" if on else "#151925")]
    if on:
        for i in range(5):
            ph = (lt * 1.6 + i * 0.37) % 1
            out.append(rect(x - 0.86 * u, y - 1.3 * u + i * 0.22 * u, 1.6 * u * (0.35 + 0.55 * hash01("l", i + int(lt * 1.6))), 0.08 * u,
                            rx=0.04 * u, fill="#ffffff", opacity=0.55 + 0.3 * ph))
    out += [path(f"M{x - 1.35 * u:.1f} {y:.1f}L{x - 1.15 * u:.1f} {y - 0.12 * u:.1f}H{x + 1.15 * u:.1f}L{x + 1.35 * u:.1f} {y:.1f}Z", fill="#9aa3b5"),
            rect(x - 1.35 * u, y - 0.02 * u, 2.7 * u, 0.08 * u, rx=0.04 * u, fill="#6d7486")]
    return "".join(out)


def p_desk(x, y, s, st, lt, style):
    u = 100 * s
    w = st.get("w", 3.6) * u
    top = y - 1.15 * u
    out = [rect(x - w / 2, top, w, 0.22 * u, rx=0.08 * u, fill="#6b4f3a"),
           rect(x - w / 2 + 0.2 * u, top + 0.2 * u, 0.16 * u, 0.95 * u, fill="#523b2b"),
           rect(x + w / 2 - 0.36 * u, top + 0.2 * u, 0.16 * u, 0.95 * u, fill="#523b2b"),
           rect(x - w / 2 + 0.05 * u, top + 0.22 * u, w - 0.1 * u, 0.4 * u, fill="#4a3628", opacity=0.6)]
    if st.get("laptop", True):
        out.append(p_laptop(x, top, s * 0.85, st, lt, style))
    return "".join(out)


def p_building(x, y, s, st, lt, style):
    u = 100 * s
    c = style.get("colors", {})
    w, h = st.get("w", 2.4) * u, st.get("h", 4.2) * u
    hacked = st.get("state") == "hacked"
    base = st.get("color") or "#2c3550"
    out = [rect(x - w / 2, y - h, w, h, rx=0.08 * u, fill=base),
           rect(x - w / 2, y - h, w * 0.18, h, fill="#ffffff", opacity=0.05)]
    cols, rows = 3, max(3, int(h / u * 1.2) - 1)
    for i in range(cols):
        for j in range(rows):
            lit = hash01(f"{x}{i}{j}") > 0.35
            col = c.get("danger", "#ff4d5e") if hacked and hash01(f"h{i}{j}") > 0.2 else ("#ffd98a" if lit else "#3a4566")
            op = 0.55 + 0.45 * math.sin(lt * 14 + i + j) if hacked else 0.9
            out.append(rect(x - w / 2 + 0.3 * u + i * (w - 0.6 * u) / cols + 0.04 * u, y - h + 0.5 * u + j * 0.62 * u,
                            (w - 0.6 * u) / cols - 0.16 * u, 0.36 * u, rx=0.04 * u, fill=col, opacity=op))
    if st.get("label"):
        f = style["fonts"]["ui"]
        fs = 0.36 * u
        tw = svg.text_width(st["label"], f["file"], fs) + 0.5 * u
        out.append(rect(x - tw / 2, y - h - 0.62 * u, tw, 0.56 * u, rx=0.12 * u, fill="#f4f1ea"))
        out.append(text(x, y - h - 0.22 * u, st["label"], f, fs, fill=INK))
    if hacked:
        e = ease_out_back(st.get("state_e", 1))
        out.append(group([path(f"M{x:.1f} {y - h * 0.62 - 0.5 * u:.1f}L{x + 0.55 * u:.1f} {y - h * 0.62 + 0.45 * u:.1f}H{x - 0.55 * u:.1f}Z",
                               fill=c.get("danger", "#ff4d5e"), stroke="#fff", stroke_width=0.06 * u, stroke_linejoin="round"),
                          text(x, y - h * 0.62 + 0.33 * u, "!", title_font(style), 0.6 * u, fill="#fff")],
                         transform=scale_about(x, y - h * 0.62, e)))
    return "".join(out)


def p_server(x, y, s, st, lt, style):
    u = 100 * s
    out = [rect(x - 0.8 * u, y - 3 * u, 1.6 * u, 3 * u, rx=0.12 * u, fill="#232a3b")]
    for j in range(5):
        yy = y - 2.8 * u + j * 0.56 * u
        out.append(rect(x - 0.65 * u, yy, 1.3 * u, 0.42 * u, rx=0.06 * u, fill="#151a27"))
        for i in range(3):
            on = (lt * 3 + hash01(f"s{j}{i}") * 5) % 1 > 0.4
            out.append(circle(x - 0.45 * u + i * 0.18 * u, yy + 0.21 * u, 0.05 * u, fill="#6fcf97" if on else "#2c3344"))
    return "".join(out)


def p_mountain(x, y, s, st, lt, style):
    u = 100 * s
    w, h = st.get("w", 6) * u, st.get("h", 4) * u
    out = [path(f"M{x - w / 2:.1f} {y:.1f}L{x:.1f} {y - h:.1f}L{x + w / 2:.1f} {y:.1f}Z", fill="#59627a"),
           path(f"M{x:.1f} {y - h:.1f}L{x + w / 2:.1f} {y:.1f}H{x + w * 0.1:.1f}Z", fill="#474f66"),
           path(f"M{x:.1f} {y - h:.1f}L{x - w * 0.12:.1f} {y - h * 0.76:.1f}L{x - w * 0.04:.1f} {y - h * 0.8:.1f}L{x + w * 0.02:.1f} {y - h * 0.72:.1f}"
                f"L{x + w * 0.12:.1f} {y - h * 0.76:.1f}Z", fill="#f4f1ea")]
    if st.get("flag"):
        out.append(p_flag(x, y - h, s * 0.8, st, lt, style))
    return "".join(out)


def p_flag(x, y, s, st, lt, style):
    u = 100 * s
    col = st.get("color") or _c(style, "accent", "#d97757")
    wave = math.sin(lt * 5) * 0.1 * u
    return (rect(x - 0.04 * u, y - 1.8 * u, 0.08 * u, 1.8 * u, fill="#c9ced8") +
            path(f"M{x + 0.04 * u:.1f} {y - 1.8 * u:.1f}Q{x + 0.5 * u:.1f} {y - 1.9 * u + wave:.1f} {x + 1 * u:.1f} {y - 1.7 * u:.1f}"
                 f"L{x + 1 * u:.1f} {y - 1.2 * u:.1f}Q{x + 0.5 * u:.1f} {y - 1.3 * u - wave:.1f} {x + 0.04 * u:.1f} {y - 1.2 * u:.1f}Z", fill=col))


def p_sign(x, y, s, st, lt, style):
    u = 100 * s
    f = style["fonts"]["ui"]
    label = st.get("label") or st.get("text") or ""
    fs = 0.42 * u
    tw = max(svg.text_width(label, f["file"], fs) + 0.7 * u, 1.6 * u)
    return (rect(x - 0.07 * u, y - 2.2 * u, 0.14 * u, 2.2 * u, fill="#7a5236") +
            rect(x - tw / 2, y - 2.6 * u, tw, 0.9 * u, rx=0.1 * u, fill="#b07a4f") +
            rect(x - tw / 2 + 0.08 * u, y - 2.52 * u, tw - 0.16 * u, 0.74 * u, rx=0.08 * u, fill="none", stroke="#8a5a3c", stroke_width=0.05 * u) +
            text(x, y - 2.0 * u, label, f, fs, fill="#fff6ea"))


def p_lamp(x, y, s, st, lt, style):
    u = 100 * s
    on = st.get("state", "on") != "off"
    out = []
    if on:
        out.append(path(f"M{x - 0.5 * u:.1f} {y - 3.0 * u:.1f}L{x - 1.6 * u:.1f} {y:.1f}H{x + 1.6 * u:.1f}L{x + 0.5 * u:.1f} {y - 3.0 * u:.1f}Z",
                        fill="url(#g-cone)", opacity=0.55))
    out += [rect(x - 0.05 * u, y - 3.0 * u, 0.1 * u, 3.0 * u, fill="#9aa3b5"),
            path(f"M{x - 0.55 * u:.1f} {y - 3.0 * u:.1f}L{x - 0.35 * u:.1f} {y - 3.7 * u:.1f}H{x + 0.35 * u:.1f}L{x + 0.55 * u:.1f} {y - 3.0 * u:.1f}Z",
                 fill="#ffe2a8" if on else "#7d8396"),
            f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{0.5 * u:.1f}" ry="{0.1 * u:.1f}" fill="#9aa3b5"/>']
    return "".join(out)


def p_bulb(x, y, s, st, lt, style):
    u = 100 * s
    on = st.get("state", "on") != "off"
    out = []
    if on:
        out.append(circle(x, y, 1.3 * u, fill="url(#g-warm)", opacity=0.6 + 0.2 * math.sin(lt * 4)))
    out += [circle(x, y, 0.62 * u, fill="#ffe08a" if on else "#7d8396"),
            rect(x - 0.3 * u, y + 0.5 * u, 0.6 * u, 0.4 * u, rx=0.08 * u, fill="#9aa3b5"),
            path(f"M{x - 0.18 * u:.1f} {y + 0.1 * u:.1f}l{0.12 * u:.1f} {-0.2 * u:.1f}l{0.12 * u:.1f} {0.2 * u:.1f}l{0.12 * u:.1f} {-0.2 * u:.1f}",
                 fill="none", stroke="#c98a1a", stroke_width=0.05 * u)]
    return "".join(out)


def p_magnifier(x, y, s, st, lt, style):
    u = 100 * s
    return (line(x + 0.45 * u, y + 0.45 * u, x + 1.1 * u, y + 1.1 * u, stroke="#6b4f3a", stroke_width=0.22 * u, stroke_linecap="round") +
            circle(x, y, 0.62 * u, fill="#bfe3ff", fill_opacity=0.35, stroke="#2d3240", stroke_width=0.14 * u) +
            path(f"M{x - 0.35 * u:.1f} {y - 0.1 * u:.1f}A{0.38 * u:.1f} {0.38 * u:.1f} 0 0 1 {x - 0.05 * u:.1f} {y - 0.4 * u:.1f}",
                 fill="none", stroke="#fff", stroke_width=0.07 * u, stroke_linecap="round", opacity=0.8))


def p_lock(x, y, s, st, lt, style):
    u = 100 * s
    c = style.get("colors", {})
    open_ = st.get("state") == "open"
    lift = 0.35 * u * ease_out_back(st.get("state_e", 1)) if open_ else 0
    col = c.get("danger", "#ff4d5e") if open_ else c.get("mustard", "#f2c14e")
    return (path(f"M{x - 0.45 * u:.1f} {y - 0.2 * u - lift:.1f}V{y - 0.65 * u - lift:.1f}A{0.45 * u:.1f} {0.45 * u:.1f} 0 0 1 {x + 0.45 * u:.1f} {y - 0.65 * u - lift:.1f}"
                 f"V{y - 0.2 * u - (0 if not open_ else lift * 0.2):.1f}", fill="none", stroke="#c9ced8", stroke_width=0.18 * u) +
            rect(x - 0.75 * u, y - 0.3 * u, 1.5 * u, 1.15 * u, rx=0.2 * u, fill=col) +
            circle(x, y + 0.2 * u, 0.13 * u, fill=INK) + rect(x - 0.05 * u, y + 0.2 * u, 0.1 * u, 0.3 * u, fill=INK))


def p_shield(x, y, s, st, lt, style):
    u = 100 * s
    c = style.get("colors", {})
    col = c.get("sage", "#6fcf97") if st.get("state") != "broken" else c.get("danger", "#ff4d5e")
    return (path(f"M{x:.1f} {y - 1.1 * u:.1f}L{x + 0.95 * u:.1f} {y - 0.75 * u:.1f}V{y - 0.05 * u:.1f}C{x + 0.95 * u:.1f} {y + 0.6 * u:.1f} {x + 0.4 * u:.1f} {y + 0.95 * u:.1f} {x:.1f} {y + 1.15 * u:.1f}"
                 f"C{x - 0.4 * u:.1f} {y + 0.95 * u:.1f} {x - 0.95 * u:.1f} {y + 0.6 * u:.1f} {x - 0.95 * u:.1f} {y - 0.05 * u:.1f}V{y - 0.75 * u:.1f}Z", fill=col) +
            path(f"M{x - 0.4 * u:.1f} {y:.1f}l{0.3 * u:.1f} {0.32 * u:.1f}l{0.55 * u:.1f} {-0.62 * u:.1f}", fill="none", stroke="#fff",
                 stroke_width=0.16 * u, stroke_linecap="round", stroke_linejoin="round"))


def p_trophy(x, y, s, st, lt, style):
    u = 100 * s
    g = "#f2c14e"
    return (path(f"M{x - 0.7 * u:.1f} {y - 1.0 * u:.1f}H{x + 0.7 * u:.1f}V{y - 0.6 * u:.1f}A{0.7 * u:.1f} {0.8 * u:.1f} 0 0 1 {x - 0.7 * u:.1f} {y - 0.6 * u:.1f}Z", fill=g) +
            path(f"M{x - 0.7 * u:.1f} {y - 0.85 * u:.1f}H{x - 1.0 * u:.1f}Q{x - 1.05 * u:.1f} {y - 0.2 * u:.1f} {x - 0.5 * u:.1f} {y - 0.15 * u:.1f}"
                 f"M{x + 0.7 * u:.1f} {y - 0.85 * u:.1f}H{x + 1.0 * u:.1f}Q{x + 1.05 * u:.1f} {y - 0.2 * u:.1f} {x + 0.5 * u:.1f} {y - 0.15 * u:.1f}",
                 fill="none", stroke=g, stroke_width=0.12 * u) +
            rect(x - 0.12 * u, y + 0.15 * u, 0.24 * u, 0.4 * u, fill="#d9a441") +
            rect(x - 0.55 * u, y + 0.5 * u, 1.1 * u, 0.3 * u, rx=0.08 * u, fill="#8a5a3c") +
            _sparkle(x + 0.45 * u, y - 0.9 * u, 0.22 * u, "#fff", lt))


def p_chart(x, y, s, st, lt, style):
    """Bar chart: ``bars`` [{label, value 0..1, color?}], grown in by ``grow`` 0..1."""
    u = 100 * s
    c = style.get("colors", {})
    bars = st.get("bars") or [{"label": "", "value": 0.4}, {"label": "", "value": 0.8}]
    g = st.get("grow", 1.0)
    n = len(bars)
    bw = 1.1 * u
    gap = 0.5 * u
    total = n * bw + (n - 1) * gap
    hmax = st.get("h", 3.2) * u
    f = style["fonts"]["ui"]
    out = [line(x - total / 2 - 0.3 * u, y, x + total / 2 + 0.3 * u, y, stroke=c.get("muted", "#888"), stroke_width=0.05 * u)]
    pal = [c.get("slate", "#6c8cff"), c.get("accent", "#d97757"), c.get("sage", "#6fcf97"), c.get("mustard", "#f2c14e")]
    for i, b in enumerate(bars):
        e = ease_out_back(clamp(g * 1.4 - i * 0.25))
        h = hmax * b.get("value", 0.5) * max(e, 0)
        bx = x - total / 2 + i * (bw + gap)
        col = b.get("color") or pal[i % len(pal)]
        out.append(rect(bx, y - h, bw, h, rx=0.16 * u, fill=col))
        if b.get("label"):
            out.append(text(bx + bw / 2, y + 0.5 * u, b["label"], f, 0.32 * u, fill=c.get("ink", "#fff")))
    return "".join(out)


def p_meter(x, y, s, st, lt, style):
    """Battery-style meter (``level`` 0..1) with an optional label above."""
    u = 100 * s
    c = style.get("colors", {})
    lvl = clamp(st.get("level", 0.5))
    w, h = 2.4 * u, 0.9 * u
    x0, y0 = x - w / 2, y - h / 2
    col = c.get("danger", "#ff4d5e") if lvl < 0.3 else c.get("mustard", "#f2c14e") if lvl < 0.6 else c.get("sage", "#6fcf97")
    out = [rect(x0, y0, w, h, rx=0.2 * u, fill="#10131c", stroke=c.get("ink", "#fff"), stroke_width=0.07 * u),
           rect(x0 + w, y - 0.18 * u, 0.14 * u, 0.36 * u, rx=0.05 * u, fill=c.get("ink", "#fff"))]
    segs = 5
    for i in range(segs):
        on = lvl * segs > i + 0.05
        out.append(rect(x0 + 0.14 * u + i * (w - 0.28 * u) / segs, y0 + 0.14 * u, (w - 0.28 * u) / segs - 0.08 * u, h - 0.28 * u,
                        rx=0.06 * u, fill=col if on else "#252b3a"))
    if st.get("label"):
        out.append(text(x, y0 - 0.3 * u, st["label"], style["fonts"]["ui"], 0.36 * u, fill=c.get("ink", "#fff"), letter_spacing=2))
    return "".join(out)


def p_lava(x, y, s, st, lt, style):
    """A molten pool across the ground with bubbles and heat glow."""
    u = 100 * s
    w = st.get("w", 9) * u
    out = [f'<ellipse cx="{x:.1f}" cy="{y - 0.4 * u:.1f}" rx="{w * 0.62:.1f}" ry="{2.2 * u:.1f}" fill="url(#g-hot)" opacity="{0.55 + 0.1 * math.sin(lt * 3):.2f}"/>',
           f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{w / 2:.1f}" ry="{0.75 * u:.1f}" fill="#d9360f"/>',
           f'<ellipse cx="{x:.1f}" cy="{y - 0.08 * u:.1f}" rx="{w / 2 - 0.3 * u:.1f}" ry="{0.55 * u:.1f}" fill="#ff6a1f"/>']
    for i in range(9):          # bright molten swirls drifting sideways
        ph = (lt * 0.25 + hash01("lv", i)) % 1
        sx = x - w * 0.42 + ((hash01("lvx", i) + lt * 0.05) % 1) * w * 0.84
        sy = y - 0.3 * u + hash01("lvy", i) * 0.45 * u
        out.append(f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" rx="{(0.35 + hash01("lr", i) * 0.4) * u:.1f}" ry="{0.07 * u:.1f}" '
                   f'fill="#ffd27a" opacity="{0.5 + 0.4 * math.sin(lt * 3 + i):.2f}"/>')
    for i in range(8):          # bubbles that rise and pop
        ph = (lt * 0.9 + hash01("lava", i)) % 1
        bx = x - w * 0.4 + hash01("lbx", i) * w * 0.8
        by = y - 0.15 * u - ph * 0.6 * u
        out.append(circle(bx, by, 0.13 * u * (1 - ph * 0.6), fill="#ffb347", opacity=round(1 - ph, 2)))
    return "".join(out)


def p_rock(x, y, s, st, lt, style):
    u = 100 * s
    return (path(f"M{x - 1.1 * u:.1f} {y:.1f}Q{x - 1.0 * u:.1f} {y - 0.9 * u:.1f} {x - 0.2 * u:.1f} {y - 1.0 * u:.1f}Q{x + 0.9 * u:.1f} {y - 1.05 * u:.1f} {x + 1.1 * u:.1f} {y:.1f}Z",
                 fill="#7d8396") +
            path(f"M{x - 0.6 * u:.1f} {y - 0.75 * u:.1f}Q{x - 0.1 * u:.1f} {y - 0.95 * u:.1f} {x + 0.4 * u:.1f} {y - 0.82 * u:.1f}", fill="none",
                 stroke="#a7adbd", stroke_width=0.08 * u, stroke_linecap="round"))


def p_star(x, y, s, st, lt, style):
    u = 100 * s
    return circle(x, y, 0.7 * u, fill="url(#g-warm)", opacity=0.55) + _sparkle(x, y, 0.42 * u, "#fff3c4", lt)


def p_phone(x, y, s, st, lt, style):
    u = 100 * s
    c = style.get("colors", {})
    return (rect(x - 0.55 * u, y - 1.0 * u, 1.1 * u, 2.0 * u, rx=0.18 * u, fill="#2b3040") +
            rect(x - 0.45 * u, y - 0.85 * u, 0.9 * u, 1.65 * u, rx=0.1 * u, fill=c.get("slate", "#6c8cff")) +
            rect(x - 0.3 * u, y - 0.6 * u, 0.6 * u, 0.14 * u, rx=0.07 * u, fill="#fff", opacity=0.7))


def p_podium(x, y, s, st, lt, style):
    u = 100 * s
    c = style.get("colors", {})
    h = st.get("h", 1.0) * u
    out = [rect(x - 0.9 * u, y - h, 1.8 * u, h, rx=0.08 * u, fill="#2c3550"),
           rect(x - 0.9 * u, y - h, 1.8 * u, 0.16 * u, rx=0.06 * u, fill=c.get("accent", "#d97757"))]
    if st.get("label"):
        out.append(text(x, y - h / 2 + 0.2 * u, st["label"], title_font(style), 0.55 * u, fill="#fff"))
    return "".join(out)


def p_plant(x, y, s, st, lt, style):
    u = 100 * s
    sway = math.sin(lt * 1.4) * 3
    leaves = [path(f"M{x:.1f} {y - 0.7 * u:.1f}Q{x + dx * u:.1f} {y - 1.3 * u:.1f} {x + dx * 1.6 * u:.1f} {y - hh * u:.1f}Q{x + dx * 0.4 * u:.1f} {y - 1.1 * u:.1f} {x:.1f} {y - 0.7 * u:.1f}Z",
                   fill="#3f9a6b" if dx > 0 else "#2f7f58") for dx, hh in ((-0.5, 1.9), (0.45, 2.1), (-0.25, 2.4), (0.2, 2.5))]
    return (group(leaves, transform=f"rotate({sway:.1f} {x:.1f} {y:.1f})") +
            path(f"M{x - 0.5 * u:.1f} {y - 0.75 * u:.1f}H{x + 0.5 * u:.1f}L{x + 0.38 * u:.1f} {y:.1f}H{x - 0.38 * u:.1f}Z", fill="#b5653e"))


def p_tower(x, y, s, st, lt, style):
    """A stack of blocks (``count``) that builds up as ``grow`` goes 0..1."""
    u = 100 * s
    n = int(st.get("count", 4))
    g = st.get("grow", 1.0)
    out = []
    for i in range(n):
        e = ease_out_bounce(clamp(g * n - i))
        if e <= 0:
            continue
        yy = y - i * 0.9 * u - (1 - e) * 2 * u
        out.append(p_block(x + (hash01("t", i) - 0.5) * 0.15 * u, yy, s, {"color": st.get("color")}, lt, style))
    return "".join(out)


PROPS = {"palm": p_palm, "block": p_block, "ball": p_ball, "hoop": p_hoop, "clock": p_clock, "note": p_note,
         "window": p_window, "terminal": p_terminal, "laptop": p_laptop, "desk": p_desk, "building": p_building,
         "server": p_server, "mountain": p_mountain, "flag": p_flag, "sign": p_sign, "lamp": p_lamp, "bulb": p_bulb,
         "magnifier": p_magnifier, "lock": p_lock, "shield": p_shield, "trophy": p_trophy, "chart": p_chart,
         "meter": p_meter, "lava": p_lava, "rock": p_rock, "star": p_star, "phone": p_phone, "podium": p_podium,
         "plant": p_plant, "tower": p_tower}
