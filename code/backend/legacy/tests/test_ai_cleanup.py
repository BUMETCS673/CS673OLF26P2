"""B1's tests for `normalize_front()` and `clean_drafts()`: one per acceptance example under
B1 in code/plans/ITERATION_3_PLAN.md, and every row of C8's examples table.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Unit test creation (from the plan's acceptance examples)
# Human role: plan review, code review, and CI verification by Duc Anh Nguyen.

import pytest

from app.ai.cleanup import clean_drafts, normalize_front
from app.ai.provider import AIUnavailable, CardDraft


def _card(front, back):
    return {"front": front, "back": back}


def _clean(raw, count=10, existing=()):
    return clean_drafts(raw, count, existing)


# C8's examples: (expected, typed, correct?)
C8_ROWS = [
    ("the library", "The Library.", True),
    ("the library", "  the   library ", True),
    ("dónde está", "¿Dónde está?", True),
    ("café", "café", True),
    ("receive", "recieve", False),
    ("adiós", "adios", False),
    ("1945", "1946", False),
    ("3.14", "314", False),
    ("C#", "C", False),
    ("anything", "", False),
    ("anything", "?", False),
]


@pytest.mark.parametrize(("expected", "typed", "correct"), C8_ROWS)
def test_normalize_front_matches_c8s_verdicts(expected, typed, correct):
    assert (normalize_front(expected) == normalize_front(typed)) is correct


def test_normalize_front_keeps_inner_punctuation_and_symbols():
    assert normalize_front("  «C#»… ") == "c#"
    assert normalize_front("3.14") == "3.14"
    assert normalize_front("-5 + $3") == "-5 + $3"
    assert normalize_front("Tab\tand\nnewline") == "tab and newline"


@pytest.mark.parametrize("raw", [{"cards": []}, None, "cards", 3])
def test_anything_but_a_list_is_unavailable(raw):
    with pytest.raises(AIUnavailable):
        _clean(raw)


def test_an_empty_list_is_no_cards():
    assert _clean([]) == []


def test_malformed_items_are_dropped():
    raw = [
        {"front": "Missing a back?"},
        {"front": 7, "back": "Seven"},
        {"front": "A list back?", "back": ["x"]},
        "not an object",
        None,
        _card("What is ATP?", "Adenosine triphosphate"),
    ]

    assert _clean(raw) == [CardDraft("What is ATP?", "Adenosine triphosphate")]


def test_both_sides_are_trimmed():
    assert _clean([_card("  What is ATP?  ", " Adenosine triphosphate ")]) == [
        CardDraft("What is ATP?", "Adenosine triphosphate")
    ]


def test_empty_or_too_long_sides_are_dropped():
    raw = [
        _card("Too long a back?", "x" * 2001),
        _card("y" * 2001, "Too long a front"),
        _card("   ", "Blank front"),
        _card("Blank back?", "\n\t"),
        _card("Just long enough?", "z" * 2000),
    ]

    assert _clean(raw) == [CardDraft("Just long enough?", "z" * 2000)]


def test_a_repeat_within_the_batch_keeps_only_the_first():
    raw = [_card("What is ATP?", "Energy carrier"), _card("what is atp", "A molecule")]

    assert _clean(raw) == [CardDraft("What is ATP?", "Energy carrier")]


def test_a_front_already_in_the_deck_is_dropped():
    raw = [_card("What is ATP?", "Energy carrier"), _card("What is DNA?", "Genetic material")]

    assert _clean(raw, existing=["  WHAT IS ATP ? "]) == [
        CardDraft("What is DNA?", "Genetic material")
    ]


def test_it_stops_at_the_count():
    raw = [_card(f"Question {i}?", f"Answer {i}") for i in range(12)]

    assert _clean(raw, count=10) == [CardDraft(f"Question {i}?", f"Answer {i}") for i in range(10)]


def test_dropped_cards_dont_use_up_the_count():
    raw = [_card("Bad?", 1)] + [_card(f"Question {i}?", f"Answer {i}") for i in range(3)]

    assert len(_clean(raw, count=3)) == 3


def test_a_front_that_gives_the_answer_away_is_dropped():
    assert _clean([_card("Is Paris the capital of France?", "Paris")]) == []
    assert _clean([_card("Is Paris the capital of France?", "paris.")]) == []


def test_a_back_inside_a_longer_word_is_kept():
    raw = [_card("What is an atom?", "a"), _card("What is 12 ÷ 6?", "2")]

    assert _clean(raw) == [CardDraft("What is an atom?", "a"), CardDraft("What is 12 ÷ 6?", "2")]


@pytest.mark.parametrize("back", ["?", "…", "¿?", "(…)"])
def test_a_back_with_no_answer_in_it_is_dropped(back):
    assert _clean([_card("What is ATP?", back)]) == []
