import json
import xml.etree.ElementTree as ET

import pytest

from reelfactory import cast, discover, render, scenes, story, timeline
from reelfactory.captions import build_chunks
from reelfactory.paths import style_for
from reelfactory.timeline import Scene, Timeline
from reelfactory.timing import Word

CAST = {"eko": {"kind": "bot", "color": "accent", "name": "Eko"},
        "res": {"kind": "person", "color": "slate", "outfit": ["labcoat", "glasses"]}}

ELEMENTS = [
    {"el": "actor", "who": "res", "id": "res", "x": 280, "enter": "walk-left", "mood": "happy",
     "do": [{"at": 0.4, "pose": "wave", "say": "See you soon!"}, {"at": 0.8, "move": [400, 1340]}],
     "out_at": 2.5, "exit": "walk-left"},
    {"el": "actor", "who": "eko", "id": "eko", "x": 700, "enter": "drop", "at": 0.2, "label": True,
     "do": [{"at": 0.6, "mood": "shock", "emote": "!"}, {"at": 1.0, "move": [760, 1260], "arc": 150}]},
    {"el": "prop", "kind": "building", "id": "hq", "x": 880, "label": "HQ", "do": [{"at": 1.0, "state": "hacked"}]},
    {"el": "prop", "kind": "terminal", "x": 540, "y": 760, "lines": ["one", "two"], "at": 0.1, "end_at": 1.0},
    {"el": "grid", "id": "g", "x": 540, "y": 800, "count": 30, "cols": 10, "w": 500, "fill_at": 0.3, "label": "sites"},
    {"el": "swarm", "from": "eko", "to": "g", "count": 8, "at": 0.3},
    {"el": "counter", "x": 540, "y": 600, "to": 50, "at": 0.2, "end_at": 1.0, "do": [{"at": 1.5, "state": "struck"},
                                                                                   {"at": 2.0, "value": 0}]},
    {"el": "stamp", "text": "too fast", "x": 540, "y": 1000, "at": 1.2},
    {"el": "label", "text": "virtual island", "x": 540, "y": 1440, "at": 0.5},
    {"el": "link", "from": "res", "to": "eko", "at": 0.5},
    {"el": "crowd", "who": "eko", "count": 3, "at": 0.4},
    {"el": "confetti", "on": "eko", "at": 0.9},
]


@pytest.fixture(scope="module")
def dark(style):
    return style_for(style, {"theme": "story"})


def params(set_name="island", **kw):
    return {"set": set_name, "elements": ELEMENTS, "_cast": CAST, "_sid": 1,
            "camera": {"moves": [{"at": 0.5, "zoom": 1.3, "focus": "eko"}], "shake": [{"at": 1.2}]},
            "title": {"text": "Playing, or *pretending?*", "at": 1.5}, **kw}


def valid(body: str, style: dict) -> None:
    ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg"><defs>{scenes.defs(style)}</defs>{body}</svg>')


@pytest.mark.parametrize("set_name", list(story.SETS))
@pytest.mark.parametrize("lt", [0.0, 0.35, 1.1, 2.0, 3.6])
def test_story_scene_is_valid_svg_in_every_set(dark, set_name, lt):
    valid(story.story_scene(lt, 3.0, params(set_name, cycle_at=0.5, virtual=True), dark), dark)


@pytest.mark.parametrize("mood", cast.MOODS)
def test_every_mood_and_pose_draws(dark, mood):
    for pose in list(cast.POSES) + ["point-left", "wave-left"]:
        valid(cast.person(500, 1300, 1, "#6c8cff", 1.3, key="p", mood=mood, pose=pose, prev_pose="idle", pose_blend=0.5,
                          outfit=["hoodie", "glasses", "tie", "cap", "headset"], name="Ann", style=dark, hold="phone"), dark)
        valid(cast.bot(500, 1300, 1, "#ff7a59", 1.3, mood=mood, pose=pose, name="Eko", style=dark), dark)


@pytest.mark.parametrize("kind", list(cast.PROPS))
def test_every_prop_draws(dark, kind):
    valid(cast.prop(kind, 540, 1000, 1.0, {"state": "hacked", "label": "x", "lines": ["a", "b"], "mark": 0}, 1.0, dark), dark)


def test_keyframes_walk_jump_and_tween():
    el = {"el": "actor", "x": 100, "_t_in": 0.0, "pose": "idle",
          "do": [{"at": 1.0, "move": [600, 1340], "dur": 1.0}, {"at": 1.2, "pose": "wave"},
                 {"at": 3.0, "move": [600, 1100], "arc": 200, "dur": 0.5}, {"at": 2.0, "level": 1.0, "dur": 1.0}]}
    mid = story.evaluate(el, 1.5, story.GROUND, 540)
    assert 100 < mid["x"] < 600 and mid["walking"] == 1.0 and mid["pose"] == "wave"
    assert story.evaluate(el, 2.5, story.GROUND, 540)["x"] == pytest.approx(600)
    assert story.evaluate(el, 2.5, story.GROUND, 540)["level"] == pytest.approx(0.5)
    jump = story.evaluate(el, 3.25, story.GROUND, 540)
    assert jump["y"] < 1100                 # the arc lifts it above the straight line
    assert story.evaluate(el, 0.5, story.GROUND, 540)["x"] == 100


def test_elements_hidden_before_their_cue_and_after_exit():
    el = {"el": "prop", "kind": "ball", "_t_in": 1.0, "out_at": 2.0, "exit": "fade"}
    assert story.enter_exit(el, 0.5, 0, 0) is None
    assert story.enter_exit(el, 1.6, 0, 0)[0] == pytest.approx(1.0)
    assert story.enter_exit(el, 2.6, 0, 0) is None


def test_story_sfx_are_sparse_and_cued():
    ev = story.sfx(params())
    assert ev and all(b[0] - a[0] >= 0.16 for a, b in zip(ev, ev[1:]))
    assert {k for _, k in ev} <= {"pop", "whoosh", "blip", "impact", "alert", "tick", "type"}


def test_title_hides_captions_and_kinetic_captions_render(dark):
    ws = [Word(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate("left alone it started to play today".split())]
    p = params()
    tl = Timeline(3.0, 2.8, [Scene("story", 0, 3.0, p, 0)], build_chunks(ws, dark, ["play"]), [])
    assert dark["captions"]["mode"] == "kinetic"
    before, after = render.frame_svg(1.0, tl, dark), render.frame_svg(2.0, tl, dark)
    assert ">alone<" in before or ">it<" in before or ">started<" in before
    assert "pretending?" in after and ">play<" not in after


@pytest.mark.parametrize("kind", ["zoom", "whip", "iris", "fade", "cut"])
def test_transitions(dark, kind):
    a, b = story.story_scene(1.0, 2, params("stage"), dark), story.story_scene(0.1, 2, params("island"), dark)
    for e in (0.0, 0.4, 0.9):
        valid("".join(render.transition(kind, e, a, b, 1080, 1920)), dark)


def test_story_cover_has_text_inside_grid(dark):
    doc = scenes.thumbnail({"label": "AI", "headline": "Left alone, it *started to play*.", "set": "island",
                            "actor": {"who": "eko", "pose": "juggle"}, "_cast": CAST}, dark)
    root = ET.fromstring(doc)
    ys = [float(t.get("y")) for t in root.iter("{http://www.w3.org/2000/svg}text") if t.get("y")]
    assert ys and all(scenes.GRID_TOP < y < scenes.GRID_BOTTOM for y in ys)


def test_timeline_injects_cast_and_story_skeleton_brief():
    sk = discover.skeleton("AI-1", {"title": "T", "source_url": "https://x"})
    assert sk["theme"] == "story" and all(s["type"] == "story" for s in sk["scenes"])
    brief = discover.BRIEF.format(handle="@me", niche="tech", title="T", url="u", source="s", summary="x",
                                  skeleton=json.dumps(sk))
    assert brief.startswith("You are helping me write") and "@me (tech)" in brief
    assert "docs/story-scenes.md" in brief and "{" in brief
    sb = {"cast": CAST, "script": "one two three", "scenes": [{"type": "story", "at": "one", "params": {"elements": []}}]}
    ws = [Word(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate("one two three".split())]
    from reelfactory.paths import load_style, Paths
    from conftest import REAL_ROOT
    st = style_for(load_style(Paths(REAL_ROOT)), sb)
    tl = timeline.build(sb, ws, 1.3, st)
    assert tl.scenes[0].params["_cast"] == CAST and st["captions"]["mode"] == "kinetic"
