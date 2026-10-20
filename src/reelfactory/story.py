"""Story scenes: characters acting out the beat in a little world, with a moving camera.

A ``story`` scene is a set (environment), a list of ``elements`` (actors, props, swarms of agent
bots, grids, counters, labels, links, stamps, confetti) and an optional camera and title. Every
element can appear on a cue (``at``), leave on a cue (``out_at``) and change on cues through its
``do`` list (move, pose, mood, look, say, emote, state, or tween a number such as ``level``).
Cues arrive already resolved to seconds since the scene started (None = not found -> defaults).

Coordinates are the 1080x1920 frame. The stage sits between the kinetic captions at the top
(y < 480) and Instagram's UI at the bottom (y > 1540); each set has a ``ground`` line (~1340).
See docs/story-scenes.md for the authoring reference.
"""
from __future__ import annotations

import math

from . import cast, svg
from .cast import hash01, mix, shade, tint
from .svg import circle, clamp, ease_in_out_cubic, ease_out_back, ease_out_cubic, group, lerp, line, path, progress, \
    rect, scale_about, text

W, H = 1080, 1920
CX = W / 2
FOCUS_Y = 1000            # the screen point the camera keeps its focus on
GROUND = 1340

SLOTS_X = {"far-left": 150, "left": 270, "left-third": 360, "center": 540, "middle": 540, "right-third": 720,
           "right": 810, "far-right": 930}
SLOTS_Y = {"top": 600, "sky": 640, "high": 760, "mid": 920, "low": 1120, "ground": None}
PALETTE_KEYS = ("accent", "slate", "sage", "mustard", "plum", "sand", "danger", "ink", "muted")
NUMERIC = ("level", "grow", "value", "size", "speed", "typed", "mark_e")


def num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def colour(v, style: dict, default: str) -> str:
    if not v:
        return default
    return style["colors"].get(v, v) if v in PALETTE_KEYS or v in style["colors"] else v


def px(v, default: float) -> float:
    if num(v):
        return float(v)
    return SLOTS_X.get(v, default) if isinstance(v, str) else default


def py(v, ground: float) -> float:
    if num(v):
        return float(v)
    if isinstance(v, str) and SLOTS_Y.get(v) is not None:
        return SLOTS_Y[v]
    return ground


# ---------------------------------------------------------------- sets (environments)


def _stars(n: int, lt: float, y1: float, op: float = 1.0) -> str:
    out = []
    for i in range(n):
        x, y = hash01("sx", i) * W, 220 + hash01("sy", i) * (y1 - 220)
        tw = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(lt * (1.2 + hash01("st", i) * 2) + i))
        out.append(circle(x, y, 1.6 + hash01("sr", i) * 2.4, fill="#fff6dd", opacity=round(tw * op * 0.9, 2)))
    return "".join(out)


def _dust(lt: float, n: int = 22, col: str = "#ffe9c7") -> str:
    out = []
    for i in range(n):
        sp = 18 + hash01("ds", i) * 30
        x = (hash01("dx", i) * W + math.sin(lt * 0.4 + i) * 30) % W
        y = 1500 - ((lt * sp + hash01("dy", i) * 1100) % 1100)
        out.append(circle(x, y, 2 + hash01("dr", i) * 3, fill=col, opacity=round(0.15 + 0.25 * hash01("do", i), 2)))
    return "".join(out)


_SID = [0]          # id suffix for gradients defined inside a scene (two scenes overlap in transitions)


def _sky(top: str, bottom: str, y1: float = H) -> str:
    gid = f"sky{_SID[0]}"
    return (f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/>'
            f'<stop offset="1" stop-color="{bottom}"/></linearGradient>' + rect(0, 0, W, y1, fill=f"url(#{gid})"))


def set_stage(lt, dur, p, style):
    c = style["colors"]
    out = [_sky(c["bg_top"], c["bg_bottom"]),
           path(f"M{CX - 120} 0L{CX - 460} {GROUND}H{CX + 460}L{CX + 120} 0Z", fill="url(#g-cone)", opacity=0.35),
           f'<ellipse cx="{CX}" cy="{GROUND + 10}" rx="470" ry="80" fill="url(#g-floor)"/>',
           rect(0, GROUND + 60, W, H - GROUND, fill="#000", opacity=0.25),
           _dust(lt)]
    return "".join(out)


def set_night(lt, dur, p, style):
    """Ref-style dark world: starry sky, a glow on the horizon, and a cross-section of soil."""
    out = [_sky("#05070d", "#141a2a", GROUND), _stars(46, lt, GROUND - 120),
           f'<ellipse cx="{CX}" cy="{GROUND}" rx="620" ry="260" fill="url(#g-warm)" opacity="0.28"/>',
           rect(0, GROUND, W, H - GROUND, fill="#15110f"),
           rect(0, GROUND, W, 10, fill="#3a2d24")]
    for i in range(5):
        y = GROUND + 70 + i * 90
        out.append(path(f"M0 {y}Q{W * 0.3} {y - 16 + i * 4} {W * 0.55} {y}T{W} {y - 6}", fill="none", stroke="#2a211b",
                        stroke_width=6, opacity=0.8))
    for i in range(40):
        out.append(circle(hash01("px", i) * W, GROUND + 30 + hash01("py", i) * 500, 2 + hash01("pr", i) * 3, fill="#3b2f27"))
    out.append(_dust(lt, 16))
    return "".join(out)


def set_island(lt, dur, p, style):
    """A small island in the sea. ``sky``: day | sunset | night; ``cycle_at`` sweeps day -> night;
    ``virtual``: true adds a faint game-world grid; ``palm``: false hides the palm tree."""
    sky = p.get("sky", "day")
    skies = {"day": ("#3f86c9", "#a9dcef", "#1f6fa8", "#0e3d6b"),
             "sunset": ("#2a2c6b", "#f29a6b", "#2b4f86", "#13284d"),
             "night": ("#060a1f", "#1b2a5c", "#10284a", "#071426")}
    cur = list(skies.get(sky, skies["day"]))
    night = 1.0 if sky == "night" else 0.0
    if num(p.get("cycle_at")):
        k = clamp((lt - p["cycle_at"]) / p.get("cycle_dur", 2.2))
        a, b, n = (skies["day"], skies["sunset"], skies["night"])
        cur = [mix(a[i], b[i], k * 2) if k < 0.5 else mix(b[i], n[i], k * 2 - 1) for i in range(4)]
        night = clamp(k * 1.6 - 0.6)
    out = [_sky(cur[0], cur[1], 1200)]
    if night > 0:
        out.append(_stars(40, lt, 1100, night))
    # sun sets / moon rises
    k_sun = clamp(lt / max(dur, 1) * 0.15) if not num(p.get("cycle_at")) else clamp((lt - p["cycle_at"]) / p.get("cycle_dur", 2.2))
    if night < 0.95:
        sy = lerp(650, 1180, k_sun if num(p.get("cycle_at")) else 0.0)
        out += [circle(820, sy, 190, fill="url(#g-warm)", opacity=0.6), circle(820, sy, 74, fill="#ffe2a0")]
    if night > 0.05:
        out += [circle(250, 640, 150, fill="url(#g-cool)", opacity=0.5 * night),
                circle(250, 640, 56, fill="#f3f0ff", opacity=night),
                circle(272, 628, 50, fill=cur[0], opacity=night)]
    if night < 0.6:
        for i in range(3):
            cx_ = (hash01("cl", i) * 1300 + lt * (12 + i * 6)) % 1400 - 160
            cy_ = 560 + i * 120
            out.append(group([f'<ellipse cx="{cx_ + dx}" cy="{cy_ + dy}" rx="{rx}" ry="{rx * 0.6:.0f}" fill="#ffffff"/>'
                              for dx, dy, rx in ((0, 0, 70), (60, -20, 60), (120, 0, 64), (60, 14, 80))],
                             opacity=round(0.55 * (1 - night), 2)))
    # sea
    out.append(f'<linearGradient id="sea{_SID[0]}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{cur[2]}"/>'
               f'<stop offset="1" stop-color="{cur[3]}"/></linearGradient>')
    out.append(rect(0, 1180, W, H - 1180, fill=f"url(#sea{_SID[0]})"))
    for i in range(6):
        y = 1210 + i * 70
        ph = lt * (24 + i * 6) % 240
        d = f"M{-240 + ph} {y}" + "".join(f"q60 -14 120 0t120 0" for _ in range(6))
        out.append(path(d, fill="none", stroke="#ffffff", stroke_width=4, opacity=0.18 - i * 0.02, stroke_linecap="round"))
    # island: side face, top face, foam
    foam = 1 + 0.02 * math.sin(lt * 2)
    out += [f'<ellipse cx="{CX}" cy="{GROUND + 70}" rx="{560 * foam:.0f}" ry="110" fill="#ffffff" opacity="0.22"/>',
            path(f"M{CX - 520} {GROUND}Q{CX - 520} {GROUND + 110} {CX - 300} {GROUND + 125}H{CX + 300}Q{CX + 520} {GROUND + 110} {CX + 520} {GROUND}Z",
                 fill="#c9955f"),
            f'<ellipse cx="{CX}" cy="{GROUND}" rx="520" ry="78" fill="#f0cf94"/>',
            f'<ellipse cx="{CX - 80}" cy="{GROUND - 18}" rx="330" ry="34" fill="#f8deaa" opacity="0.7"/>']
    if p.get("virtual"):
        sh = 0.25 + 0.15 * math.sin(lt * 3)
        g = []
        for i in range(-6, 7):
            g.append(line(CX + i * 80, GROUND - 74, CX + i * 95, GROUND + 74, stroke="#7fd4ff", stroke_width=2))
        for j in range(-2, 3):
            g.append(f'<ellipse cx="{CX}" cy="{GROUND}" rx="{520 - abs(j) * 0}" ry="{78 - abs(j) * 24}" fill="none" stroke="#7fd4ff" stroke-width="2"/>')
        out.append(group(g, opacity=round(sh, 2)))
    if p.get("palm", True):
        out.append(cast.p_palm(px(p.get("palm_x"), 880), GROUND + 6, 1.15, {}, lt, style))
    for i, (gx, gs) in enumerate(((250, 1), (430, 0.8), (700, 0.9))):
        out.append(path(f"M{gx} {GROUND + 10}q-6 -26 -16 -34M{gx} {GROUND + 10}q2 -30 4 -40M{gx} {GROUND + 10}q8 -24 18 -30",
                        fill="none", stroke="#6aa85a", stroke_width=5 * gs, stroke_linecap="round"))
    return "".join(out)


def set_office(lt, dur, p, style):
    out = [_sky("#1a2030", "#121620"),
           rect(140, 470, 420, 520, rx=18, fill="#0d1220"), rect(150, 480, 400, 500, rx=12, fill="#18233d")]
    for i in range(28):
        bx, bh = 160 + (i % 7) * 56, 120 + hash01("b", i) * 300
        out.append(rect(bx, 980 - bh, 46, bh, fill="#24304d"))
        for j in range(int(bh / 40)):
            if hash01("w", i * 13 + j) > 0.55:
                out.append(rect(bx + 10 + (j % 2) * 16, 990 - bh + j * 40, 10, 14, fill="#ffd98a", opacity=0.7))
    out += [line(350, 480, 350, 980, stroke="#0d1220", stroke_width=10), line(150, 730, 550, 730, stroke="#0d1220", stroke_width=10),
            rect(0, GROUND - 20, W, H - GROUND + 20, fill="#1b1f2b"), rect(0, GROUND - 20, W, 8, fill="#2a3042"),
            cast.p_lamp(900, GROUND - 16, 1.0, {}, lt, style), _dust(lt, 14)]
    return "".join(out)


def set_lab(lt, dur, p, style):
    out = [_sky("#0f2a2c", "#0a1617")]
    for i in range(3):
        x = 150 + i * 300
        on = 0.7 + 0.3 * math.sin(lt * 2 + i)
        out += [rect(x, 520, 240, 160, rx=14, fill="#0b1314", stroke="#24464a", stroke_width=4),
                rect(x + 14, 534, 212, 132, rx=8, fill="#1d5a5e", opacity=on)]
        for j in range(4):
            out.append(rect(x + 30, 556 + j * 26, 60 + hash01("lab", i * 9 + j) * 120, 8, rx=4, fill="#7ff0e0", opacity=0.6))
    out += [rect(0, GROUND - 20, W, H - GROUND + 20, fill="#0d1a1b"), rect(0, GROUND - 20, W, 8, fill="#24464a"),
            _dust(lt, 14, "#c9fff6")]
    for i in range(10):
        out.append(line(i * 120, GROUND - 12, i * 120 - 260, H, stroke="#163032", stroke_width=3))
    return "".join(out)


def set_city(lt, dur, p, style):
    out = [_sky("#0a0f22", "#2a2048"), _stars(26, lt, 800, 0.8),
           circle(820, 600, 60, fill="#f3f0ff", opacity=0.9)]
    for layer, (col, base, hmin, hmax, wmin) in enumerate((("#1a1f3d", GROUND - 40, 260, 520, 90), ("#121630", GROUND, 180, 380, 70))):
        x = -20
        i = 0
        while x < W + 40:
            w = wmin + hash01(f"cw{layer}", i) * 70
            h = hmin + hash01(f"ch{layer}", i) * (hmax - hmin)
            out.append(rect(x, base - h, w - 8, h, fill=col))
            for j in range(int(h / 46)):
                for k in range(int(w / 30)):
                    if hash01(f"cl{layer}{i}", j * 7 + k) > 0.68:
                        out.append(rect(x + 10 + k * 26, base - h + 18 + j * 46, 12, 18, fill="#ffd98a", opacity=0.55 + layer * 0.2))
            x += w
            i += 1
    out += [rect(0, GROUND, W, H - GROUND, fill="#0c0f1c"), rect(0, GROUND, W, 6, fill="#2a3042")]
    return "".join(out)


def set_cyber(lt, dur, p, style):
    c = style["colors"]
    out = [_sky("#070a16", "#101634")]
    hz = 1080
    for i in range(-10, 11):
        out.append(line(CX + i * 40, hz, CX + i * 260, H, stroke=c["slate"], stroke_width=2, opacity=0.35))
    for j in range(9):
        k = ((j + (lt * 0.6) % 1) / 9) ** 2
        y = hz + k * (H - hz)
        out.append(line(0, y, W, y, stroke=c["slate"], stroke_width=2, opacity=round(0.1 + 0.3 * k, 2)))
    nodes = [(hash01("nx", i) * W, 560 + hash01("ny", i) * 440) for i in range(12)]
    for i, (x, y) in enumerate(nodes):
        a, b = nodes[(i * 5 + 3) % 12]
        out.append(line(x, y, a, b, stroke=c["slate"], stroke_width=2, opacity=0.2))
    for i, (x, y) in enumerate(nodes):
        out.append(circle(x, y + math.sin(lt + i) * 8, 5, fill="#9fb6ff", opacity=0.7))
    out.append(f'<ellipse cx="{CX}" cy="{hz}" rx="700" ry="120" fill="url(#g-cool)" opacity="0.5"/>')
    return "".join(out)


def set_room(lt, dur, p, style):
    """Cosy dark room with a warm lamp (like the battery-meter reference)."""
    out = [_sky("#232838", "#171a26"),
           rect(0, GROUND - 20, W, H - GROUND + 20, fill="#1c1f2c"),
           f'<ellipse cx="{CX}" cy="{GROUND + 20}" rx="430" ry="60" fill="#2a2f42"/>',
           cast.p_lamp(130, GROUND - 10, 1.05, {}, lt, style), cast.p_plant(980, GROUND - 10, 1.0, {}, lt, style), _dust(lt, 12)]
    for i in range(12):
        x = 60 + i * 90
        out.append(path(f"M{x} 470l45 60l45 -60", fill=["#d97757", "#6c8cff", "#f2c14e", "#6fcf97"][i % 4], opacity=0.7))
    out.append(path("M40 470Q540 500 1040 470", fill="none", stroke="#9aa3b5", stroke_width=3, opacity=0.6))
    return "".join(out)


SETS = {"stage": set_stage, "void": set_stage, "night": set_night, "island": set_island, "office": set_office,
        "lab": set_lab, "city": set_city, "cyber": set_cyber, "room": set_room}


# ---------------------------------------------------------------- keyframes


def _tween_value(tweens: list[tuple[float, float, float, float]], lt: float, base: float) -> float:
    """tweens: (t0, dur, from, to) in time order -> value at lt."""
    v = base
    for t0, d, a, b in tweens:
        if lt < t0:
            break
        v = lerp(a, b, ease_in_out_cubic(progress(lt, t0, d)))
    return v


def evaluate(el: dict, lt: float, ground: float, default_x: float) -> dict:
    """The element's state at lt: position (with walking/arcs), pose blend, mood, bubble, emote, tweens."""
    x0, y0 = px(el.get("x"), default_x), py(el.get("y"), ground)
    st = {k: v for k, v in el.items() if k not in ("do",)}
    st.update(x=x0, y=y0, pose=el.get("pose", "idle"), prev_pose=None, pose_t=-99.0, mood=el.get("mood", "neutral"),
              mood_t=-99.0, look=el.get("look"), state=el.get("state"), state_t=-99.0, say=None, emote=None, walking=0.0,
              moving=False, dir=0.0)
    t_in = el.get("_t_in", 0.0)
    segs: list[tuple[float, float, float, float, float, float, float]] = []
    ent = el.get("enter", "")
    if ent in ("walk-left", "walk-right", "fly-left", "fly-right"):
        sx = -240 if ent.endswith("left") else W + 240
        segs.append((t_in, max(0.6, abs(x0 - sx) / 560), sx, y0, x0, y0, 0.0))
    cur = (x0, y0)
    tweens: dict[str, list] = {}
    vals = {k: el[k] for k in NUMERIC if num(el.get(k))}
    keys = sorted((k for k in el.get("do", []) if num(k.get("at"))), key=lambda k: k["at"])
    for k in keys:
        t = k["at"]
        if "move" in k or "to" in k:
            m = k.get("move", k.get("to"))
            if isinstance(m, (list, tuple)) and len(m) == 2:
                nx, ny = px(m[0], cur[0]), py(m[1], ground)
            elif isinstance(m, dict):
                nx, ny = px(m.get("x"), cur[0]), py(m.get("y"), ground) if "y" in m else cur[1]
            else:
                nx, ny = px(m, cur[0]), cur[1]
            d = math.hypot(nx - cur[0], ny - cur[1])
            dur = k.get("dur") or clamp(d / 560, 0.35, 1.8)
            segs.append((t, dur, cur[0], cur[1], nx, ny, float(k.get("arc", 0))))
            cur = (nx, ny)
        for f in NUMERIC:
            if num(k.get(f)):
                prev = _tween_value(tweens.get(f, []), t, vals.get(f, 0.0 if f != "size" else el.get("size", 1.0)))
                tweens.setdefault(f, []).append((t, k.get("dur") or 0.6, prev, float(k[f])))
        if t > lt:
            continue
        if "pose" in k:
            st["prev_pose"], st["pose"], st["pose_t"] = st["pose"], k["pose"], t
        if "mood" in k:
            st["mood"], st["mood_t"] = k["mood"], t
        if "look" in k:
            st["look"] = k["look"]
        if "say" in k:
            txt = str(k["say"])
            st["say"] = (txt, t, k.get("for") or max(1.5, 0.5 + len(txt) * 0.06))
        if "emote" in k:
            st["emote"] = (k["emote"], t)
        if "state" in k:
            st["state"], st["state_t"] = k["state"], t
        if "hold" in k:
            st["hold"] = k["hold"]
        for f in ("label", "title", "text", "color", "lines", "bars", "mark"):
            if f in k:
                st[f] = k[f]
                if f == "mark":
                    st["mark_t"] = t
    x, y = x0, y0
    for t0, d, ax, ay, bx, by, arc in segs:
        if lt < t0:
            break
        e = progress(lt, t0, d)
        ee = ease_in_out_cubic(e) if arc == 0 else e
        x, y = lerp(ax, bx, ee), lerp(ay, by, ee)
        if arc:
            y -= arc * 4 * e * (1 - e)
        if e < 1:
            st["moving"] = True
            st["walking"] = 0.0 if arc else 1.0
            st["dir"] = math.copysign(1, bx - ax) if bx != ax else 0
    st["x"], st["y"] = x, y
    for f in NUMERIC:
        if f in tweens or f in vals:
            st[f] = _tween_value(tweens.get(f, []), lt, vals.get(f, 0.0 if f != "size" else el.get("size", 1.0)))
    return st


def look_vec(v, moving_dir: float) -> tuple[float, float]:
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return float(v[0]), float(v[1])
    m = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1), "center": (0, 0), "up-left": (-0.8, -0.7),
         "up-right": (0.8, -0.7), "down-left": (-0.8, 0.6), "down-right": (0.8, 0.6)}
    if isinstance(v, str) and v in m:
        return m[v]
    return (moving_dir, 0.0)


# ---------------------------------------------------------------- entrances / exits

DEFAULT_ENTER = {"actor": "pop", "prop": "pop", "label": "rise", "counter": "rise", "grid": "pop", "link": "fade",
                 "stamp": "slam", "confetti": "none", "swarm": "none", "crowd": "pop", "text": "rise"}
GROW_PROPS = {"building", "mountain", "tower", "server", "palm", "hoop", "podium", "plant"}
RISE_PROPS = {"window", "terminal", "note", "chart", "meter"}


def enter_exit(el: dict, lt: float, ax: float, ay: float) -> tuple[float, str] | None:
    """(opacity, transform) for the element's entrance/exit, or None while it is hidden."""
    t_in = el.get("_t_in", 0.0)
    if lt < t_in - 1e-6:
        return None
    kind = el.get("enter") or DEFAULT_ENTER.get(el["el"], "pop")
    if el["el"] == "prop" and not el.get("enter"):
        kind = "grow" if el.get("kind") in GROW_PROPS else "rise" if el.get("kind") in RISE_PROPS else "pop"
    e = progress(lt, t_in, {"drop": 0.8, "slam": 0.35}.get(kind, 0.5))
    op, tr = 1.0, ""
    if kind == "pop":
        s = ease_out_back(e)
        op, tr = min(1.0, e * 4), scale_about(ax, ay, max(s, 0.001))
    elif kind == "drop":
        op, tr = 1.0, f"translate(0 {-(1 - cast.ease_out_bounce(e)) * 900:.1f})"
    elif kind == "rise":
        op, tr = ease_out_cubic(e), f"translate(0 {(1 - ease_out_cubic(e)) * 70:.1f})"
    elif kind == "grow":
        s = ease_out_back(e)
        op, tr = min(1.0, e * 5), f"translate({ax:.1f} {ay:.1f}) scale(1 {max(s, 0.001):.4f}) translate({-ax:.1f} {-ay:.1f})"
    elif kind == "slam":
        s = lerp(2.4, 1.0, ease_out_cubic(e))
        op, tr = min(1.0, e * 3), scale_about(ax, ay, s)
    elif kind == "fade":
        op = ease_out_cubic(e)
    out_t = el.get("out_at")
    if num(out_t) and lt >= out_t:
        x = progress(lt, out_t, 0.4)
        if x >= 1:
            return None
        ex = el.get("exit", "pop")
        if ex == "pop":
            tr += " " + scale_about(ax, ay, max(1 - ease_in_out_cubic(x) * 1.0, 0.001))
            op *= 1 - x * 0.6
        elif ex in ("walk-left", "walk-right"):
            pass                                           # handled as a move by the caller
        elif ex == "drop":
            tr += f" translate(0 {ease_in_out_cubic(x) * 900:.1f})"
        else:
            op *= 1 - x
    return op, tr


# ---------------------------------------------------------------- element drawing


def _cast_entry(el: dict, castmap: dict, style: dict) -> dict:
    who = el.get("who")
    base = dict(castmap.get(who, {})) if who else {}
    if not base and who:
        base = {"kind": "bot" if "bot" in str(who) or "agent" in str(who) else "person"}
    for k in ("kind", "color", "outfit", "name", "eye"):
        if k in el:
            base[k] = el[k]
    base.setdefault("kind", "person")
    base["color"] = colour(base.get("color"), style, style["colors"]["accent"] if base["kind"] == "bot" else style["colors"]["slate"])
    return base


def actor_top(kind: str, x: float, y: float, size: float) -> tuple[float, float]:
    u = 100 * size
    return (x, y - (3.25 if kind == "person" else 3.0) * u)


def draw_actor(el: dict, st: dict, lt: float, style: dict, castmap: dict) -> str:
    ce = _cast_entry(el, castmap, style)
    size = st.get("size", el.get("size", 1.0 if ce["kind"] == "person" else 0.9))
    lk = look_vec(st.get("look"), st.get("dir", 0.0))
    if st.get("look") is None and not st.get("moving") and num(el.get("_look_seed")):
        ph = (lt * 0.35 + el["_look_seed"] * 3) % 3
        lk = (-0.6, 0) if ph < 0.8 else (0.6, 0) if 1.5 < ph < 2.2 else (0, 0)
    name = el.get("label") if isinstance(el.get("label"), str) else (ce.get("name") if el.get("label") else None)
    react = 1 - progress(lt, st.get("mood_t", -99), 0.4)
    pb = progress(lt, st.get("pose_t", -99), 0.3)
    kw = dict(key=el.get("id") or el.get("_key", "a"), pose=st["pose"], prev_pose=st.get("prev_pose"), pose_blend=pb,
              mood=st["mood"], look=lk, walking=st.get("walking", 0.0), hold=st.get("hold"), name=name, style=style,
              tilt=st.get("tilt", el.get("tilt", 0.0)))
    if ce["kind"] == "bot":
        body = cast.bot(st["x"], st["y"], size, ce["color"], lt, eye=ce.get("eye", "#ffe9d2"), outfit=ce.get("outfit", ()), **kw)
    else:
        body = cast.person(st["x"], st["y"], size, ce["color"], lt, outfit=ce.get("outfit", ()), **kw)
    if react > 0:
        k = 1 + 0.07 * math.sin(react * math.pi)
        body = group(body, transform=f"translate({st['x']:.1f} {st['y']:.1f}) scale({2 - k:.4f} {k:.4f}) translate({-st['x']:.1f} {-st['y']:.1f})")
    extra = []
    tx, ty = actor_top(ce["kind"], st["x"], st["y"], size)
    if st.get("emote"):
        kind_, t0 = st["emote"]
        e = progress(lt, t0, 0.35)
        fade = 1 - progress(lt, t0 + 1.6, 0.3)
        if fade > 0:
            extra.append(group(cast.emote(kind_, tx + 80 * size, ty - 30, size, e, lt, style), opacity=fade))
    if st.get("say"):
        txt, t0, d = st["say"]
        e = progress(lt, t0, 0.3)
        fade = 1 - progress(lt, t0 + d, 0.25)
        if fade > 0:
            side = -1 if st["x"] > 640 else 1
            extra.append(group(cast.bubble(txt, tx + side * 30 * size, ty - 10, e, style, side), opacity=fade))
    return body + "".join(extra)


def _prop_state(el: dict, st: dict, lt: float) -> dict:
    s = dict(st)
    s["state_e"] = progress(lt, st.get("state_t", -99), 0.4)
    t_in = el.get("_t_in", 0.0)
    end = el.get("end_at")
    span = (end - t_in) if num(end) and end > t_in else el.get("dur", 1.4)
    p = progress(lt, t_in + 0.2, span)
    if el.get("kind") in ("window", "terminal") and "typed" not in el and el.get("lines"):
        s["typed"] = len(el["lines"]) * p if el.get("type", True) else len(el["lines"])
    if el.get("kind") in ("chart", "tower") and "grow" not in el:
        s["grow"] = p
    if el.get("kind") == "note" and el.get("mark") is not None:
        s["mark_e"] = progress(lt, el.get("mark_at", st.get("mark_t", t_in + 0.4)) if num(el.get("mark_at", st.get("mark_t"))) else t_in + 0.4, 0.5)
    if el.get("kind") == "ball":
        s["spin"] = lt * 360 if st.get("moving") else 0
    if el.get("kind") == "hoop" and num(el.get("swish_at")):
        s["swish"] = progress(lt, el["swish_at"], 0.5)
    return s


def draw_prop(el: dict, st: dict, lt: float, style: dict) -> str:
    s = _prop_state(el, st, lt)
    body = cast.prop(el.get("kind", "block"), st["x"], st["y"], st.get("size", el.get("size", 1.0)), s, lt, style)
    if el.get("glow"):
        body = (f'<ellipse cx="{st["x"]:.1f}" cy="{st["y"]:.1f}" rx="{220 * st.get("size", 1):.0f}" ry="{180 * st.get("size", 1):.0f}" '
                f'fill="url(#g-{el["glow"] if isinstance(el["glow"], str) else "warm"})" opacity="0.55"/>') + body
    if st.get("state") == "hacked" or el.get("shake_on_state"):
        k = 1 - progress(lt, st.get("state_t", -99), 0.5)
        if k > 0:
            body = group(body, transform=f"translate({math.sin(lt * 70) * 10 * k:.1f} 0)")
    return body


def grid_cells(el: dict) -> list[tuple[float, float]]:
    n = int(el.get("count", 100))
    cols = int(el.get("cols", 10))
    rows = math.ceil(n / cols)
    w = el.get("w", 700)
    cell = w / cols
    x0 = px(el.get("x"), CX) - w / 2 + cell / 2
    y0 = py(el.get("y"), 800) - rows * cell / 2 + cell / 2
    return [(x0 + (i % cols) * cell, y0 + (i // cols) * cell) for i in range(n)]


def _fill_order(n: int, key: str) -> list[int]:
    return sorted(range(n), key=lambda i: hash01(key, i))


def draw_grid(el: dict, lt: float, style: dict) -> str:
    """A grid of small icons (sites, people, dots) that turn ``fill`` colour between fill_at and end_at."""
    c = style["colors"]
    cells = grid_cells(el)
    n = len(cells)
    w = el.get("w", 700)
    cell = w / max(int(el.get("cols", 10)), 1)
    t_in = el.get("_t_in", 0.0)
    if lt < t_in:
        return ""
    f0 = el.get("fill_at") if num(el.get("fill_at")) else None
    f1 = el.get("end_at") if num(el.get("end_at")) else (f0 + 2.4 if f0 is not None else None)
    fill_to = el.get("fill_to", 1.0)
    filled = 0.0
    if f0 is not None:
        filled = ease_in_out_cubic(progress(lt, f0, max(f1 - f0, 0.3))) * fill_to * n
    order = _fill_order(n, el.get("id", "grid"))
    rank = {i: r for r, i in enumerate(order)}
    fcol = colour(el.get("fill"), style, c.get("danger", "#ff4d5e"))
    base = colour(el.get("color"), style, "#3a4258")
    icon = el.get("icon", "site")
    out = []
    for i, (x, y) in enumerate(cells):
        appear = ease_out_back(progress(lt, t_in + (i % 10) * 0.025 + (i // 10) * 0.03, 0.35))
        if appear <= 0:
            continue
        r = rank[i]
        on = r < filled
        pop = 1 + 0.25 * math.sin(clamp(filled - r) * math.pi) if on and r > filled - 1.5 else 1
        col = fcol if on else base
        s = cell * 0.78 * appear * pop
        if icon == "dot":
            out.append(circle(x, y, s * 0.42, fill=col))
        elif icon == "person":
            out.append(circle(x, y - s * 0.2, s * 0.2, fill=col))
            out.append(path(f"M{x - s * 0.32:.1f} {y + s * 0.38:.1f}Q{x:.1f} {y - s * 0.12:.1f} {x + s * 0.32:.1f} {y + s * 0.38:.1f}Z", fill=col))
        else:
            out.append(rect(x - s / 2, y - s / 2, s, s * 0.82, rx=s * 0.14, fill=col))
            out.append(rect(x - s / 2, y - s / 2, s, s * 0.2, rx=s * 0.1, fill=shade(col, 0.25)))
            out.append(rect(x - s * 0.36, y - s * 0.12, s * 0.5, s * 0.1, rx=s * 0.05, fill="#ffffff", opacity=0.55))
            out.append(rect(x - s * 0.36, y + s * 0.06, s * 0.68, s * 0.08, rx=s * 0.04, fill="#ffffff", opacity=0.3))
    if el.get("label"):
        rows = math.ceil(n / max(int(el.get("cols", 10)), 1))
        top = py(el.get("y"), 800) - rows * cell / 2 - 36
        lbl = el["label"]
        if el.get("counter", True) and f0 is not None:
            lbl = f"{int(round(min(filled, n)))} {lbl}"
        out.append(text(px(el.get("x"), CX), top, lbl.upper(), style["fonts"]["ui"], 34, fill=c["ink"], letter_spacing=4))
    return "".join(out)


def draw_counter(el: dict, st: dict, lt: float, style: dict) -> str:
    """A big number that counts up (and can be re-set through ``do`` entries with ``value``)."""
    c = style["colors"]
    t_in = el.get("_t_in", 0.0)
    end = el.get("end_at") if num(el.get("end_at")) else t_in + el.get("dur", 1.2)
    a, b = float(el.get("from", 0)), float(el.get("to", 100))
    v = lerp(a, b, ease_out_cubic(progress(lt, t_in, max(end - t_in, 0.2))))
    for k in sorted((k for k in el.get("do", []) if num(k.get("at")) and num(k.get("value"))), key=lambda k: k["at"]):
        if lt >= k["at"]:
            v = lerp(v, float(k["value"]), ease_out_cubic(progress(lt, k["at"], k.get("dur", 0.6))))
    x, y = st["x"], st["y"]
    size = el.get("font", 170) * st.get("size", 1.0)
    f = cast.title_font(style)
    col = colour(st.get("color"), style, c["ink"])
    txt = f"{el.get('prefix', '')}{int(round(v)):,}{el.get('suffix', '')}"
    out = [text(x, y, txt, f, size, fill=col, stroke="#0b0d14", stroke_width=size * 0.06, paint_order="stroke",
                stroke_linejoin="round")]
    if st.get("label") or el.get("label"):
        out.append(text(x, y + size * 0.42, str(st.get("label") or el.get("label")).upper(), style["fonts"]["ui"], size * 0.2,
                        fill=c["muted"], letter_spacing=4))
    if st.get("state") == "struck":
        e = ease_out_cubic(progress(lt, st.get("state_t", -99), 0.3))
        tw = svg.text_width(txt, f["file"], size)
        out.append(line(x - tw / 2 - 20, y - size * 0.32, x - tw / 2 - 20 + (tw + 40) * e, y - size * 0.32 + 8 * e,
                        stroke=c.get("danger", "#ff4d5e"), stroke_width=size * 0.09, stroke_linecap="round"))
    return "".join(out)


def draw_label(el: dict, st: dict, lt: float, style: dict) -> str:
    c = style["colors"]
    x, y = st["x"], st["y"]
    txt = str(st.get("text") or el.get("text", ""))
    kind = el.get("variant", "tag")
    if kind == "plain":
        return text(x, y, txt.upper(), style["fonts"]["ui"], el.get("font", 36), fill=c["ink"], letter_spacing=6)
    if kind == "big":
        f = cast.title_font(style)
        return text(x, y, txt, f, el.get("font", 84), fill=colour(st.get("color"), style, c["ink"]), stroke="#0b0d14",
                    stroke_width=8, paint_order="stroke", stroke_linejoin="round")
    f = style["fonts"]["ui"]
    fs = el.get("font", 34)
    tw = svg.text_width(txt, f["file"], fs) + fs * 1.4
    col = colour(st.get("color"), style, c["accent"])
    out = [rect(x - tw / 2, y - fs * 1.05, tw, fs * 1.7, rx=fs * 0.85, fill=col),
           text(x, y + fs * 0.12, txt, f, fs, fill="#ffffff" if col != c.get("ink") else "#111")]
    if el.get("arrow"):
        out.append(path(f"M{x - 14:.1f} {y + fs * 0.65:.1f}L{x:.1f} {y + fs * 0.65 + 18:.1f}L{x + 14:.1f} {y + fs * 0.65:.1f}Z", fill=col))
    return "".join(out)


def draw_stamp(el: dict, st: dict, lt: float, style: dict) -> str:
    c = style["colors"]
    x, y = st["x"], st["y"]
    txt = str(st.get("text") or el.get("text", "")).upper()
    f = cast.title_font(style)
    fs = el.get("font", 74)
    col = colour(st.get("color"), style, c.get("danger", "#ff4d5e"))
    tw = svg.text_width(txt, f["file"], fs) + fs * 0.9
    body = [rect(x - tw / 2, y - fs * 0.95, tw, fs * 1.35, rx=fs * 0.18, fill="none", stroke=col, stroke_width=fs * 0.1),
            text(x, y + fs * 0.08, txt, f, fs, fill=col)]
    return group(body, transform=f"rotate({el.get('rotate', -8)} {x:.1f} {y:.1f})", opacity=0.92)


def draw_link(el: dict, anchors: dict, lt: float, style: dict) -> str:
    c = style["colors"]
    a, b = _point(el.get("from"), anchors), _point(el.get("to"), anchors)
    if a is None or b is None:
        return ""
    t_in = el.get("_t_in", 0.0)
    e = ease_in_out_cubic(progress(lt, t_in, 0.6))
    bend = el.get("bend", -120)
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + bend
    col = colour(el.get("color"), style, c["accent"])

    def q(t):
        return ((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * mx + t * t * b[0], (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * my + t * t * b[1])
    pts = [q(i / 24 * e) for i in range(25)]
    d = "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    out = [path(d, fill="none", stroke=col, stroke_width=6, stroke_dasharray="4 16", stroke_linecap="round", opacity=0.8)]
    if e >= 1:
        for k in range(3):
            tx, ty = q(((lt * 0.7) + k / 3) % 1)
            out.append(circle(tx, ty, 10, fill=col))
    return "".join(out)


def _point(ref, anchors: dict):
    if isinstance(ref, (list, tuple)) and len(ref) == 2:
        return px(ref[0], CX), py(ref[1], GROUND)
    if isinstance(ref, str) and ref in anchors:
        return anchors[ref]["mid"]
    return None


def draw_swarm(el: dict, anchors: dict, grids: dict, lt: float, style: dict, castmap: dict) -> str:
    """Agent bots launched from ``from`` that fly to ``to`` (a grid, an element id, or points) and get busy there."""
    n = int(min(el.get("count", 10), 40))
    t_in = el.get("_t_in", 0.0)
    src = _point(el.get("from"), anchors) or (CX, 1200)
    tgt = el.get("to")
    cells = None
    if isinstance(tgt, str) and tgt in grids:
        cells = grid_cells(grids[tgt])
    elif isinstance(tgt, list) and tgt and all(isinstance(t, str) for t in tgt):
        cells = [anchors[t]["mid"] for t in tgt if t in anchors]
    elif isinstance(tgt, list) and tgt and isinstance(tgt[0], (list, tuple)):
        cells = [_point(t, anchors) for t in tgt]
    else:
        p = _point(tgt, anchors)
        cells = [p] if p else [(CX, 800)]
    ce = _cast_entry({"who": el.get("who") or "agent", "kind": "bot", **({"color": el["color"]} if el.get("color") else {})},
                     castmap, style)
    size = el.get("size", 0.3)
    stagger = el.get("stagger", 0.07)
    hop = el.get("hop", 0.75)
    out = []
    for i in range(n):
        t0 = t_in + i * stagger
        if lt < t0:
            continue
        k0 = int(hash01(el.get("id", "sw"), i) * 997)
        a = src
        b = cells[k0 % len(cells)]
        fly = 0.85
        trail = ""
        if lt < t0 + fly:
            e = progress(lt, t0, fly)
            ee = ease_in_out_cubic(e)
            hgt = 220 + hash01("swh", i) * 260
            x = lerp(a[0], b[0], ee)
            y = lerp(a[1], b[1], ee) - hgt * 4 * ee * (1 - ee)
            tilt = (b[0] - a[0]) / 40
            for j in range(1, 5):
                ej = clamp(ee - j * 0.05)
                tx_ = lerp(a[0], b[0], ej)
                ty_ = lerp(a[1], b[1], ej) - hgt * 4 * ej * (1 - ej)
                trail += circle(tx_, ty_ - 30 * size * 3, 7 - j, fill=ce["color"], opacity=0.35 - j * 0.07)
        else:
            k = int((lt - t0 - fly) / hop) if cells and len(cells) > 1 and el.get("roam", True) else 0
            tloc = (lt - t0 - fly) - k * hop
            prev = cells[(k0 + (k - 1) * 37) % len(cells)] if k > 0 else b
            nxt = cells[(k0 + k * 37) % len(cells)] if k > 0 else b
            e = ease_in_out_cubic(clamp(tloc / (hop * 0.6))) if k > 0 else 1
            x, y = lerp(prev[0], nxt[0], e), lerp(prev[1], nxt[1], e) - 60 * math.sin(e * math.pi)
            tilt = math.sin(lt * 4 + i) * 6
            if e >= 1 and tloc < hop * 0.9:
                z = progress(tloc, hop * 0.6, 0.25)
                trail += circle(nxt[0], nxt[1], 26 * (1 + z), fill="none", stroke="#ffd27a", stroke_width=4, opacity=round(1 - z, 2))
        out.append(trail)
        out.append(cast.bot(x, y + 40 * size * 2, size, ce["color"], lt, key=f"{el.get('id', 'sw')}{i}", mood=el.get("mood", "focused"),
                            style=style, eye=ce.get("eye", "#ffe9d2"), tilt=tilt))
    return "".join(out)


def draw_crowd(el: dict, lt: float, style: dict, castmap: dict) -> str:
    """A row of identical characters (copies, a team, an audience) popping in one after another."""
    n = int(min(el.get("count", 3), 12))
    t_in = el.get("_t_in", 0.0)
    xs = el.get("xs")
    if not xs:
        x0, x1 = px(el.get("x0"), 200), px(el.get("x1"), 880)
        xs = [lerp(x0, x1, i / max(n - 1, 1)) for i in range(n)] if n > 1 else [CX]
    y = py(el.get("y"), GROUND)
    ce = _cast_entry(el, castmap, style)
    size = el.get("size", 0.8 if ce["kind"] == "bot" else 0.8)
    out = []
    moods = el.get("moods") or [el.get("mood", "happy")]
    for i, x in enumerate(xs):
        e = progress(lt, t_in + i * el.get("stagger", 0.15), 0.45)
        if e <= 0:
            continue
        mood = moods[i % len(moods)]
        pose = el.get("pose", "idle")
        name = el.get("label") if isinstance(el.get("label"), str) else (ce.get("name") if el.get("label") else None)
        fn = cast.bot if ce["kind"] == "bot" else cast.person
        kw = dict(key=f"{el.get('id', 'crowd')}{i}", mood=mood, pose=pose, style=style, name=name,
                  look=((CX - x) / 900, 0))
        if ce["kind"] == "bot":
            kw["eye"] = ce.get("eye", "#ffe9d2")
        else:
            kw["outfit"] = ce.get("outfit", ())
        body = fn(x, y, size, ce["color"], lt + i * 0.37, **kw)
        out.append(group(body, transform=scale_about(x, y, max(ease_out_back(e), 0.001)), opacity=min(1, e * 4)))
    return "".join(out)


def draw_confetti(el: dict, anchors: dict, lt: float, style: dict) -> str:
    c = style["colors"]
    t_in = el.get("_t_in", 0.0)
    if lt < t_in or lt > t_in + 2.2:
        return ""
    o = _point(el.get("on"), anchors) or (px(el.get("x"), CX), py(el.get("y"), 900))
    cols = [c["accent"], c["mustard"], c["sage"], c["slate"], c["plum"]]
    out = []
    t = lt - t_in
    for i in range(int(el.get("count", 36))):
        a = hash01("cf", i) * 2 * math.pi
        sp = 500 + hash01("cs", i) * 700
        x = o[0] + math.cos(a) * sp * t * 0.8
        y = o[1] + math.sin(a) * sp * t * 0.8 - 300 * t + 900 * t * t
        r = hash01("cr", i) * 360 + t * 400
        out.append(rect(x - 9, y - 5, 18, 10, rx=3, fill=cols[i % len(cols)], opacity=round(clamp(1.6 - t * 0.8), 2),
                        transform=f"rotate({r:.0f} {x:.1f} {y:.1f})"))
    return "".join(out)


# ---------------------------------------------------------------- camera + title


def camera(p: dict, lt: float, dur: float, anchors: dict) -> tuple[float, float, float, float, float]:
    """(zoom, focus x, focus y, shake x, shake y) at lt."""
    cam = p.get("camera") or {}
    z = float(cam.get("zoom", 1.0))
    f = _point(cam.get("focus"), anchors) or (CX, FOCUS_Y)
    fx, fy = f
    for m in sorted((m for m in cam.get("moves", []) if num(m.get("at"))), key=lambda m: m["at"]):
        if lt < m["at"]:
            break
        e = ease_in_out_cubic(progress(lt, m["at"], m.get("dur", 0.8)))
        nf = _point(m.get("focus"), anchors) or (fx, fy)
        z = lerp(z, float(m.get("zoom", z)), e)
        fx, fy = lerp(fx, nf[0], e), lerp(fy, nf[1], e)
    drift = cam.get("drift", 0.045)
    z *= 1 + drift * ease_in_out_cubic(clamp(lt / max(dur, 0.5)))
    sx = sy = 0.0
    for s in cam.get("shake", []):
        if num(s.get("at")) and s["at"] <= lt < s["at"] + s.get("dur", 0.45):
            k = 1 - (lt - s["at"]) / s.get("dur", 0.45)
            amp = s.get("amp", 16) * k
            sx += math.sin(lt * 63) * amp
            sy += math.cos(lt * 51) * amp * 0.7
    return z, fx, fy, sx, sy


def cam_transform(z: float, fx: float, fy: float, sx: float, sy: float, depth: float = 1.0) -> str:
    z = 1 + (z - 1) * depth
    fx = CX + (fx - CX) * depth
    fy = FOCUS_Y + (fy - FOCUS_Y) * depth
    return f"translate({CX + sx * depth:.1f} {FOCUS_Y + sy * depth:.1f}) scale({z:.4f}) translate({-fx:.1f} {-fy:.1f})"


def title_window(p: dict) -> tuple[float, float] | None:
    t = p.get("title")
    if not t or not t.get("text"):
        return None
    t0 = t["at"] if num(t.get("at")) else 0.0
    t1 = t["out_at"] if num(t.get("out_at")) else 1e9
    return t0, t1


def draw_title(p: dict, lt: float, style: dict) -> str:
    """Big punchline words that pop in one by one; *accent* words go in the accent colour."""
    from .scenes import parse_rich, wrap_rich
    t = p["title"]
    win = title_window(p)
    if win is None or lt < win[0]:
        return ""
    f = cast.title_font(style)
    size = t.get("size", 104)
    lines_ = wrap_rich(t["text"], f["file"], size, 940)
    y0 = t.get("y", 640)
    lh = size * 1.06
    out = []
    k = 0
    fade = 1 - progress(lt, win[1], 0.3)
    for li, ln in enumerate(lines_):
        words = [(w[1:] if w.startswith("\x00") else w, a, w.startswith("\x00")) for w, a in ln]
        widths = [svg.text_width(w, f["file"], size) for w, _, _ in words]
        sp = size * 0.26
        total = sum(widths) + sp * sum(1 for _, _, g in words[1:] if not g)
        x = CX - total / 2
        for (w, acc, glued), wd in zip(words, widths):
            if glued:
                x -= sp
            e = progress(lt, win[0] + k * 0.09, 0.32)
            s = ease_out_back(e)
            cx_, cy_ = x + wd / 2, y0 + li * lh - size * 0.35
            col = style["colors"]["accent"] if acc else style["colors"]["ink"]
            out.append(group(text(x, y0 + li * lh, w, f, size, fill=col, anchor="start", stroke="#0b0d14",
                                  stroke_width=size * 0.09, paint_order="stroke", stroke_linejoin="round"),
                             transform=scale_about(cx_, cy_, max(s, 0.001)), opacity=min(1, e * 3)))
            x += wd + sp
            k += 1
    return group(out, opacity=fade)


# ---------------------------------------------------------------- the scene


def prepare(p: dict) -> list[dict]:
    """Elements with defaults filled in (ids, entrance times, x for actors without one)."""
    raw = p.get("elements", [])
    kinds = [e.get("el", "actor" if "who" in e else "prop") for e in raw]
    auto = [i for i, (e, k) in enumerate(zip(raw, kinds)) if k == "actor" and "x" not in e]
    spots = {1: [CX], 2: [330, 750], 3: [230, 540, 850], 4: [180, 410, 670, 900]}.get(len(auto))
    els = []
    for i, (e, k) in enumerate(zip(raw, kinds)):
        e = dict(e)
        e["el"] = k
        e["_key"] = e.get("id") or f"e{i}"
        e["_t_in"] = e["at"] if num(e.get("at")) else 0.05 + 0.12 * i
        if i in auto and spots:
            e["x"] = spots[auto.index(i)]
        e["_look_seed"] = hash01(e["_key"])
        els.append(e)
    return els


def story_scene(lt: float, dur: float, p: dict, style: dict) -> str:
    set_fn = SETS.get(p.get("set", "stage"), set_stage)
    _SID[0] = p.get("_sid", 0)
    ground = GROUND
    castmap = p.get("_cast") or {}
    els = prepare(p)
    states, anchors, grids = {}, {}, {}
    for i, e in enumerate(els):
        if e["el"] in ("actor", "prop", "counter", "label", "stamp", "text"):
            st = evaluate(e, lt, ground, CX)
            if num(e.get("out_at")) and lt >= e["out_at"] and e.get("exit") in ("walk-left", "walk-right"):
                k = progress(lt, e["out_at"], 1.0)
                tx = -260 if e["exit"] == "walk-left" else W + 260
                st["x"] = lerp(st["x"], tx, ease_in_out_cubic(k))
                st["walking"], st["dir"] = 1.0, -1 if e["exit"] == "walk-left" else 1
            states[e["_key"]] = st
            mid = (st["x"], st["y"])
            if e["el"] == "actor":
                ce = _cast_entry(e, castmap, style)
                top = actor_top(ce["kind"], st["x"], st["y"], st.get("size", e.get("size", 1.0 if ce["kind"] == "person" else 0.9)))
                mid = (st["x"], (st["y"] + top[1]) / 2)
            elif e["el"] == "prop" and e.get("kind") in cast.GROUNDED:
                mid = (st["x"], st["y"] - 120 * st.get("size", e.get("size", 1.0)))
            anchors[e["_key"]] = {"mid": mid, "x": st["x"], "y": st["y"]}
        elif e["el"] == "grid":
            grids[e["_key"]] = e
            anchors[e["_key"]] = {"mid": (px(e.get("x"), CX), py(e.get("y"), 800))}
    z, fx, fy, sx, sy = camera(p, lt, dur, anchors)
    world = []
    for e in els:
        kind = e["el"]
        st = states.get(e["_key"])
        if kind in ("swarm", "confetti", "link"):
            if lt < e["_t_in"]:
                continue
            if kind == "swarm":
                world.append(draw_swarm(e, anchors, grids, lt, style, castmap))
            elif kind == "confetti":
                world.append(draw_confetti(e, anchors, lt, style))
            else:
                world.append(draw_link(e, anchors, lt, style))
            continue
        if kind == "grid":
            world.append(draw_grid(e, lt, style))
            continue
        if kind == "crowd":
            world.append(draw_crowd(e, lt, style, castmap))
            continue
        if st is None:
            continue
        ee = enter_exit(e, lt, st["x"], st["y"] if kind in ("actor", "prop") else st["y"])
        if ee is None:
            continue
        op, tr = ee
        if kind == "actor":
            body = draw_actor(e, st, lt, style, castmap)
        elif kind == "prop":
            body = draw_prop(e, st, lt, style)
        elif kind == "counter":
            body = draw_counter(e, st, lt, style)
        elif kind == "stamp":
            body = draw_stamp(e, st, lt, style)
        else:
            body = draw_label(e, st, lt, style)
        world.append(group(body, transform=tr or None, opacity=op))
    out = [group(set_fn(lt, dur, p, style), transform=cam_transform(z, fx, fy, sx, sy, 0.55)),
           group(world, transform=cam_transform(z, fx, fy, sx, sy))]
    if p.get("title"):
        out.append(draw_title(p, lt, style))
    out.append(rect(0, 0, W, H, fill="url(#g-vig)"))
    return "".join(out)


# ---------------------------------------------------------------- sound cues


def sfx(p: dict) -> list[tuple[float, str]]:
    """Sound effects implied by the scene (local seconds): pops, whooshes, blips, impacts."""
    ev: list[tuple[float, str]] = []
    for i, e in enumerate(prepare(p)):
        t = e["_t_in"]
        kind = e["el"]
        if num(e.get("at")):
            if kind == "swarm":
                ev.append((t, "whoosh"))
            elif kind == "stamp":
                ev.append((t + 0.12, "impact"))
            elif kind == "confetti":
                ev.append((t, "pop"))
            elif kind in ("actor", "crowd") and str(e.get("enter", "")).startswith(("walk", "fly")):
                ev.append((t, "whoosh"))
            elif kind == "actor" and e.get("enter") == "drop":
                ev.append((t + 0.3, "impact"))
            elif kind in ("actor", "prop", "label", "counter", "crowd", "grid"):
                ev.append((t, "pop"))
        if kind == "grid" and num(e.get("fill_at")):
            ev.append((e["fill_at"], "alert"))
        if kind == "prop" and e.get("kind") in ("terminal", "window") and e.get("lines"):
            ev.append((t + 0.2, "type"))
        for k in e.get("do", []):
            if not num(k.get("at")):
                continue
            if "emote" in k or "say" in k:
                ev.append((k["at"], "blip"))
            elif k.get("state") in ("hacked", "struck", "open", "broken"):
                ev.append((k["at"], "alert" if k["state"] == "hacked" else "impact"))
            elif "move" in k and k.get("arc"):
                ev.append((k["at"], "whoosh"))
            elif "mood" in k:
                ev.append((k["at"], "tick"))
    cam = p.get("camera") or {}
    for s in cam.get("shake", []):
        if num(s.get("at")):
            ev.append((s["at"], "impact"))
    win = title_window(p)
    if win and win[0] > 0:
        ev.append((win[0], "whoosh"))
    ev.sort()
    out: list[tuple[float, str]] = []
    for t, k in ev:                       # keep it sparse: no two cues closer than 0.16 s
        if out and t - out[-1][0] < 0.16:
            continue
        out.append((t, k))
    return out
