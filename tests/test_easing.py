from reelfactory import svg


def test_easing_endpoints():
    for fn in (svg.ease_out_cubic, svg.ease_in_cubic, svg.ease_in_out_cubic, svg.ease_out_expo, svg.ease_out_back):
        assert abs(fn(0)) < 1e-9
        assert abs(fn(1) - 1) < 1e-9


def test_progress_clamps():
    assert svg.progress(-1, 0, 1) == 0
    assert svg.progress(0.5, 0, 1) == 0.5
    assert svg.progress(5, 0, 1) == 1
    assert svg.progress(1, 1, 0) == 1


def test_group_skips_invisible():
    assert svg.group(["<rect/>"], opacity=0) == ""
    assert svg.group([""]) == ""
    assert 'opacity="0.5"' in svg.group(["<rect/>"], opacity=0.5)


def test_text_is_escaped():
    out = svg.text(0, 0, 'A & "B" <C>', {"family": "Inter", "weight": 600}, 20)
    assert "&amp;" in out and "&lt;C&gt;" in out


def test_text_width_scales(style):
    f = style["fonts"]["caption"]["file"]
    assert svg.text_width("HELLO", f, 100) > svg.text_width("HELLO", f, 50) > 0
