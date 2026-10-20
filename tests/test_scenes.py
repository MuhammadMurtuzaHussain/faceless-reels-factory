from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

import pytest

from reelfactory import render, scenes
from reelfactory.captions import build_chunks
from reelfactory.timeline import Scene, Timeline
from reelfactory.timing import Word

VISUALS = {
    "apps": {"type": "apps"},
    "rows": {"type": "rows", "rows": [{"icon": "pin", "label": "Location", "detail": "Where", "value": "Live", "at": 0.5},
                                       {"icon": "moon", "label": "Sleep", "value": "00:47", "at": None}]},
    "connect": {"type": "connect", "connect_at": 1.0, "predict_at": None},
    "feed": {"type": "feed", "ads_at": 0.8, "sort_at": 1.6},
    "consent": {"type": "consent", "dim_at": 1.0, "follow": True},
}


def card(visual, **kw):
    return {"label": "Step", "headline": "Your data is worth *more* than you think.", "sub": "Sub line",
            "_step": "01 / 05", "visual": visual, **kw}


@pytest.mark.parametrize("kind", list(VISUALS))
@pytest.mark.parametrize("lt", [0.0, 0.2, 1.1, 2.9, 3.4])
def test_card_scene_produces_valid_svg(style, kind, lt):
    body = scenes.card_scene(lt, 3.0, card(VISUALS[kind]), style)
    ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg"><defs>{scenes.defs(style)}</defs>{body}</svg>')


def test_headline_swap(style):
    p = card(None, headline2="What am I *actually trading?*", swap_at=1.0)
    before, after = scenes.card_scene(0.9, 3, p, style), scenes.card_scene(2.0, 3, p, style)
    assert "trading?" not in before and "trading?" in after


def test_rich_text_keeps_punctuation_attached(style):
    words = scenes.parse_rich("Not just your *name*. Tap *Accept all*…")
    assert ("name", True) in words
    assert scenes.plain(words) == "Not just your name. Tap Accept all…"
    lines = scenes.wrap_rich("It decides *what you see*.", style["fonts"]["headline"]["file"], 80, 780)
    assert len(lines) == 2 and len(lines[-1]) > 1          # balanced: no lonely last word


def test_full_frame_through_transition(style):
    ws = [Word(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate("one two three four five six".split())]
    sc = [Scene("card", 0, 1.2, card(VISUALS["apps"]), 0), Scene("card", 1.2, 2.6, card(VISUALS["rows"]), 3)]
    tl = Timeline(2.6, 2.4, sc, build_chunks(ws, style, []), [])
    for t in (0.0, 1.25, 1.35, 2.5):
        root = ET.fromstring(render.frame_svg(t, tl, style))
        assert root.get("width") == "1080" and root.get("height") == "1920"


def test_bundled_fonts_really_render(style):
    from reelfactory.paths import Paths
    from conftest import REAL_ROOT
    assert all(render.font_check(Paths(REAL_ROOT), style).values())


@pytest.mark.parametrize("lt", [0.0, 0.5, 1.3, 2.5])
def test_endcard_shows_profile_photo(style, lt):
    p = {"label": "Before you go", "headline": "One AI story, *every day*.", "follow_at": 1.2}
    body = scenes.endcard_scene(lt, 3.0, p, style)
    ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg"><defs>{scenes.defs(style)}</defs>{body}</svg>')
    if lt >= 0.5:
        from pathlib import Path
        prof = style.get("profile") or {}
        if prof.get("avatar") and Path(prof["avatar"]).exists():
            assert "data:image/jpeg;base64," in body
        assert escape(prof.get("name", "")) in body


def test_thumbnail_is_a_full_cover_with_text_inside_the_grid_crop(style):
    doc = scenes.thumbnail({"label": "AI scams", "headline": "Scammers cloned a *sheriff's voice*."}, style)
    root = ET.fromstring(doc)
    assert root.get("width") == "1080" and root.get("height") == "1920"
    ys = [float(t.get("y")) for t in root.iter("{http://www.w3.org/2000/svg}text")]
    assert ys and all(scenes.GRID_TOP < y < scenes.GRID_BOTTOM for y in ys)


def test_cta_end_card_spoken_and_silent(style):
    from reelfactory import cta, timeline
    sb = {"script": "one two three four", "scenes": [{"type": "card", "at": "one", "params": {"headline": "Hi"}}]}
    spoken = cta.spoken_script(sb, style).split()
    ws = [Word(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate(spoken)]
    tl = timeline.build({**sb, "scenes": sb["scenes"] + [cta.scene(sb, style, True)]}, ws, ws[-1].end + 0.2, style)
    end = tl.scenes[-1]
    assert end.start == pytest.approx(ws[4].start - 0.12) and end.params["_step"] == ""
    assert tl.scenes[0].params["_step"] == "01 / 01" and tl.duration >= end.start + 2.5
    ws = ws[:4]                                       # hand recording: the CTA isn't spoken
    tl = timeline.build({**sb, "scenes": sb["scenes"] + [cta.scene(sb, style, False)]}, ws, 1.6, style)
    assert tl.scenes[-1].start == pytest.approx(1.75) and tl.duration == pytest.approx(1.75 + 2.8)
    assert cta.scene({**sb, "cta": False}, style, True) is None
