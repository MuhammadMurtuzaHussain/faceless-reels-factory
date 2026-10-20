import pytest

from reelfactory.timing import Word, align, distribute, find_phrase, fix_monotonic, normalize, tokenize_script


def test_normalize_and_tokenize():
    assert normalize("You'll,") == "youll"
    assert tokenize_script('tap "accept all", ask — one') == ['tap', '"accept', 'all",', 'ask', 'one']


def test_align_exact_match():
    script = ["Every", "app", "you", "open."]
    heard = [Word("Every", 0.0, 0.3), Word("app", 0.3, 0.5), Word("you", 0.5, 0.7), Word("open.", 0.7, 1.0)]
    words, ratio = align(script, heard, 1.2)
    assert ratio == 1.0
    assert [w.start for w in words] == [0.0, 0.3, 0.5, 0.7]


def test_align_interpolates_misheard_words():
    script = ["Your", "location.", "Your", "habits."]
    heard = [Word("Your", 0.0, 0.2), Word("vocation", 0.2, 0.8), Word("Your", 0.8, 1.0), Word("habits", 1.0, 1.4)]
    words, ratio = align(script, heard, 2.0)
    assert ratio == 0.75
    assert words[1].text == "location."          # script spelling wins
    assert 0.2 <= words[1].start < words[2].start
    assert all(a.start <= b.start for a, b in zip(words, words[1:]))


def test_distribute_respects_segments():
    words = distribute(["one", "two", "three", "four"], [(0.5, 1.5), (2.5, 3.5)])
    assert words[0].start >= 0.5
    assert words[-1].end <= 3.5
    assert all(a.start <= b.start for a, b in zip(words, words[1:]))


def test_fix_monotonic_clamps_to_duration():
    ws = [Word("a", 0.5, 0.4), Word("b", 0.3, 9.0)]
    fix_monotonic(ws, 2.0)
    assert ws[0].end >= ws[0].start and ws[1].start >= ws[0].start and ws[1].end <= 2.0


def test_find_phrase():
    words = [Word(w, i, i + 1) for i, w in enumerate("so before you tap accept all what am I".split())]
    assert find_phrase(words, "what am") == 6
    assert find_phrase(words, "Before you", 0) == 1
    with pytest.raises(ValueError):
        find_phrase(words, "not here")
