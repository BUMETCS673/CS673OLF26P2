"""Tests for the scheduling rules (Lab 3, Story 1).

Every expected number here is what Anki's default scheduler gives for the same card and
button, checked against Anki's source (rslib/src/scheduler/states/). The rows follow the
acceptance examples in code/plans/LAB_3_PLAN.md, Story 1.

`answer_card()` is pure, so these are plain asserts: no database, no app, no clock.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.scheduler import CardSchedule, CardState, Rating, answer_card

NOW = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
DAY = timedelta(days=1)


def new_card():
    return CardSchedule(CardState.NEW, None, 0, 2500, 0, 0)


def learning(step):
    return CardSchedule(CardState.LEARNING, NOW, 0, 2500, step, 0)


def review(interval, ease=2500, overdue=timedelta(0), lapses=0):
    return CardSchedule(CardState.REVIEW, NOW - overdue, interval, ease, 0, lapses)


def relearning(interval=1, ease=2300, lapses=1):
    return CardSchedule(CardState.RELEARNING, NOW, interval, ease, 0, lapses)


# ---- new and learning cards ----------------------------------------------


@pytest.mark.parametrize(
    ("rating", "state", "step", "due_in"),
    [
        (Rating.AGAIN, CardState.LEARNING, 0, 1 * MINUTE),
        (Rating.HARD, CardState.LEARNING, 0, timedelta(seconds=330)),  # (1m + 10m) / 2
        (Rating.GOOD, CardState.LEARNING, 1, 10 * MINUTE),
        (Rating.EASY, CardState.REVIEW, 0, 4 * DAY),
    ],
)
def test_a_new_card_starts_on_the_first_learning_step(rating, state, step, due_in):
    after = answer_card(new_card(), rating, NOW)

    assert after.state is state
    assert after.step == step
    assert after.due_at == NOW + due_in


def test_easy_on_a_new_card_graduates_it_straight_to_a_4_day_review():
    after = answer_card(new_card(), Rating.EASY, NOW)

    assert (after.interval_days, after.ease_factor) == (4, 2500)


def test_good_on_the_last_learning_step_graduates_to_a_1_day_review():
    after = answer_card(learning(step=1), Rating.GOOD, NOW)

    assert after.state is CardState.REVIEW
    assert (after.interval_days, after.ease_factor, after.step) == (1, 2500, 0)
    assert after.due_at == NOW + DAY


def test_again_on_any_learning_step_goes_back_to_the_first():
    after = answer_card(learning(step=1), Rating.AGAIN, NOW)

    assert (after.state, after.step) == (CardState.LEARNING, 0)
    assert after.due_at == NOW + MINUTE


def test_hard_on_a_later_learning_step_repeats_that_step():
    after = answer_card(learning(step=1), Rating.HARD, NOW)

    assert (after.state, after.step) == (CardState.LEARNING, 1)
    assert after.due_at == NOW + 10 * MINUTE


def test_easy_on_a_later_learning_step_still_graduates_to_4_days():
    after = answer_card(learning(step=1), Rating.EASY, NOW)

    assert (after.state, after.interval_days) == (CardState.REVIEW, 4)


# ---- review cards --------------------------------------------------------


@pytest.mark.parametrize(
    ("interval", "ease", "overdue_days", "expected"),
    [
        (1, 2500, 0, {"hard": 2, "good": 3, "easy": 4}),  # the minimums decide all three
        (10, 2500, 0, {"hard": 12, "good": 25, "easy": 33}),  # 32.5 rounds up, as in Anki
        (10, 2500, 4, {"hard": 12, "good": 30, "easy": 46}),  # lateness counts for Good/Easy
        (100, 2300, 7, {"hard": 120, "good": 238, "easy": 320}),
        (45, 1300, 0, {"hard": 54, "good": 58, "easy": 76}),  # the 32-bit case: 58, not 59
        (20000, 2500, 0, {"hard": 24000, "good": 36500, "easy": 36500}),  # the cap
    ],
)
@pytest.mark.parametrize("rating", [Rating.HARD, Rating.GOOD, Rating.EASY])
def test_review_intervals_match_anki(interval, ease, overdue_days, expected, rating):
    card = review(interval, ease, overdue=overdue_days * DAY)

    after = answer_card(card, rating, NOW)

    days = expected[rating.value]
    assert after.state is CardState.REVIEW
    assert after.interval_days == days
    assert after.due_at == NOW + days * DAY
    assert after.step == 0


def test_only_whole_days_overdue_count():
    # 36 hours late counts as 1 day, not 1.5: Good is (10 + 1/2) x 2.5 = 26.25 -> 26.
    card = review(10, overdue=timedelta(hours=36))

    assert answer_card(card, Rating.GOOD, NOW).interval_days == 26


def test_an_early_answer_is_scored_as_if_on_time():
    # Anki has a separate early-review formula; we don't implement it (decision L7), and
    # story 5 refuses early answers before they get here.
    card = review(10, overdue=-DAY)

    assert answer_card(card, Rating.GOOD, NOW).interval_days == 25


@pytest.mark.parametrize(
    ("ease", "rating", "expected_ease"),
    [
        (2500, Rating.HARD, 2350),
        (2500, Rating.GOOD, 2500),
        (2500, Rating.EASY, 2650),  # no ceiling
        (1400, Rating.HARD, 1300),  # floored at 130%
        (1300, Rating.HARD, 1300),
    ],
)
def test_passing_a_review_adjusts_the_ease(ease, rating, expected_ease):
    after = answer_card(review(10, ease), rating, NOW)

    assert after.ease_factor == expected_ease


def test_again_on_a_review_card_sends_it_to_relearning():
    after = answer_card(review(30, lapses=0), Rating.AGAIN, NOW)

    assert (after.state, after.step) == (CardState.RELEARNING, 0)
    assert after.due_at == NOW + 10 * MINUTE
    assert (after.ease_factor, after.lapses, after.interval_days) == (2300, 1, 1)


def test_again_never_takes_the_ease_below_130_percent():
    after = answer_card(review(30, ease=1300), Rating.AGAIN, NOW)

    assert after.ease_factor == 1300


# ---- relearning cards ----------------------------------------------------


def test_again_while_relearning_restarts_the_step_and_keeps_ease_and_lapses():
    after = answer_card(relearning(), Rating.AGAIN, NOW)

    assert (after.state, after.step) == (CardState.RELEARNING, 0)
    assert after.due_at == NOW + 10 * MINUTE
    assert (after.interval_days, after.ease_factor, after.lapses) == (1, 2300, 1)


def test_hard_while_relearning_waits_one_and_a_half_steps():
    after = answer_card(relearning(), Rating.HARD, NOW)

    assert after.state is CardState.RELEARNING
    assert after.due_at == NOW + 15 * MINUTE


@pytest.mark.parametrize(("rating", "days"), [(Rating.GOOD, 1), (Rating.EASY, 2)])
def test_passing_the_relearning_step_returns_the_card_to_review(rating, days):
    after = answer_card(relearning(), rating, NOW)

    assert (after.state, after.step, after.interval_days) == (CardState.REVIEW, 0, days)
    assert after.due_at == NOW + days * DAY
    assert (after.ease_factor, after.lapses) == (2300, 1)  # unchanged since the lapse


# ---- inputs --------------------------------------------------------------


def test_a_rating_can_be_passed_as_its_string():
    assert answer_card(new_card(), "good", NOW) == answer_card(new_card(), Rating.GOOD, NOW)


def test_an_unknown_rating_is_refused():
    with pytest.raises(ValueError):
        answer_card(new_card(), "great", NOW)


def test_an_unknown_state_is_refused():
    paused = CardSchedule("paused", None, 0, 2500, 0, 0)

    with pytest.raises(ValueError):
        answer_card(paused, Rating.GOOD, NOW)
