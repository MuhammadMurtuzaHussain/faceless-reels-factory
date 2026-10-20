from reelfactory.captions import build_chunks, render
from reelfactory.timing import Word
from reelfactory.timeline import Timeline
from reelfactory.validate import validate_timeline


def words(text, step=0.3):
    return [Word(w, i * step, i * step + step * 0.9) for i, w in enumerate(text.split())]


def test_chunks_respect_max_words_and_punctuation(style):
    chunks = build_chunks(words("Not just your name. Your location. Your habits and everything else"), style, [])
    assert all(len(c.words) <= style["captions"]["max_words"] for c in chunks)
    assert chunks[0].display == ["Not", "just", "your", "name"]   # break after the full stop
    assert chunks[1].display == ["Your", "location"]


def test_chunks_fit_safe_zone_and_do_not_overlap(style):
    ws = words("Incomprehensibilities supercalifragilistic connected together predict what you'll buy")
    chunks = build_chunks(ws, style, ["predict"])
    tl = Timeline(10, 9, [], chunks, [])
    checks = validate_timeline(tl, style)
    assert all(c.ok for c in checks if c.name.startswith("caption")), checks


def test_emphasis_and_render(style):
    chunks = build_chunks(words("they can help predict"), style, ["predict"])
    assert any(any(c.emphasis) for c in chunks)
    svg_out = render(chunks[-1].words[-1].start + 0.1, chunks, style)
    assert style["colors"]["accent"] in svg_out
    assert render(99, chunks, style) == ""


def test_display_strips_quotes_and_trailing_punctuation():
    from reelfactory.captions import display_text
    assert display_text('all",', False) == "all"
    assert display_text('"accept', True) == "ACCEPT"
    assert display_text("trading?", True) == "TRADING?"
