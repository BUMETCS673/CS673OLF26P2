"""Anki's scheduling algorithm: when each card is next due (Lab 3, Story 1).

Step 0a wrote the interface below and Story 1 fills in `answer_card()`. Stories 2 and 5
code against these names too, so they're frozen -- see "The scheduler interface" in
code/plans/LAB_3_PLAN.md before changing any of them.

This module is pure (rule 7 in the plan). It imports nothing from Flask, SQLAlchemy, or
app.models, and it never reads the clock: `now` is always passed in, UTC-aware.
`Card.schedule` converts between a database row and a `CardSchedule`.
"""

import math
import struct
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum


class CardState(StrEnum):
    """Where a card is in Anki's cycle. Stored as these strings in `cards.state`."""

    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"


class Rating(StrEnum):
    """The learner's four buttons, spelled the way the API sends them."""

    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


@dataclass(frozen=True)
class CardSchedule:
    """Everything the scheduler knows about a card."""

    state: CardState
    due_at: datetime | None   # UTC-aware. None only while new
    interval_days: int        # while relearning: the interval the card goes back to
    ease_factor: int          # thousandths: 2500 = 250%
    step: int                 # which learning or relearning step, from 0
    lapses: int               # times failed from review


# Anki's default deck options, named after the labels on Anki's deck-options screen.
LEARNING_STEPS = (timedelta(minutes=1), timedelta(minutes=10))
GRADUATING_INTERVAL_DAYS = 1
EASY_INTERVAL_DAYS = 4
RELEARNING_STEPS = (timedelta(minutes=10),)
MINIMUM_INTERVAL_DAYS = 1
MAXIMUM_INTERVAL_DAYS = 36500
STARTING_EASE = 2500
EASY_BONUS = 1.3
HARD_INTERVAL = 1.2
NEW_INTERVAL = 0.0            # a failed review card's interval is multiplied by this

# Fixed in Anki's code rather than set per deck.
EASE_AGAIN = -200
EASE_HARD = -150
EASE_EASY = 150
MINIMUM_EASE = 1300

# How much one session serves (Story 2). LEARN_AHEAD is mirrored in
# frontend/src/study/constants.js -- change both together.
LEARN_AHEAD = timedelta(minutes=20)
NEW_CARDS_PER_SESSION = 20
REVIEWS_PER_SESSION = 200


def answer_card(card: CardSchedule, rating: Rating, now: datetime) -> CardSchedule:
    """The card's schedule after the learner answers it with `rating` at `now`.

    Anki's default scheduler with Anki's default settings, minus the random fuzz Anki
    adds to review intervals (decision L1). Written from the rules in the plan, not
    translated from Anki's source (decision D5).

    An answer before a review card is due is scored as if on time: Anki's early-review
    formula isn't implemented, and the review endpoint refuses early answers (L7).
    """
    rating = Rating(rating)  # accepts "good" as well as Rating.GOOD; refuses anything else
    card = replace(card, state=CardState(card.state))
    if card.state is CardState.REVIEW:
        return _answer_review(card, rating, now)
    return _answer_in_steps(card, rating, now)


# B3 (Von) -- AI Utilization: 90% | AI Tools Used: Claude |
# AI-Assisted Activities: scheduler preview function
def preview_intervals(card: CardSchedule, now: datetime) -> dict[Rating, timedelta]:
    """How long after `now` the card would be due for each rating, if answered at `now`.

    Pure, like `answer_card()`: it only asks the scheduler, and saves nothing (B3).
    """
    return {rating: answer_card(card, rating, now).due_at - now for rating in Rating}


def _answer_in_steps(card: CardSchedule, rating: Rating, now: datetime) -> CardSchedule:
    """New, learning, and relearning cards: short steps measured in minutes.

    A new card is answered as if it were on the first learning step.
    """
    relearning = card.state is CardState.RELEARNING
    steps = RELEARNING_STEPS if relearning else LEARNING_STEPS
    state = CardState.RELEARNING if relearning else CardState.LEARNING
    step = min(card.step, len(steps) - 1)

    if rating is Rating.AGAIN:
        # A relearning card recomputes the interval it will go back to, the same way the
        # failed review did. Learning cards have no interval yet.
        interval = _failed_interval(card.interval_days) if relearning else card.interval_days
        return replace(card, state=state, step=0, due_at=now + steps[0], interval_days=interval)
    if rating is Rating.HARD:
        return replace(card, state=state, step=step, due_at=now + _hard_delay(steps, step))
    if rating is Rating.GOOD and step + 1 < len(steps):
        return replace(card, state=state, step=step + 1, due_at=now + steps[step + 1])

    # Good on the last step, or Easy on any step: the card goes (back) to review.
    if relearning:
        # The ease and lapses already changed when the review failed.
        bonus_day = 1 if rating is Rating.EASY else 0
        return _to_review(card, card.interval_days + bonus_day, now)
    days = EASY_INTERVAL_DAYS if rating is Rating.EASY else GRADUATING_INTERVAL_DAYS
    return _to_review(replace(card, ease_factor=STARTING_EASE), days, now)


def _hard_delay(steps: tuple[timedelta, ...], step: int) -> timedelta:
    """Hard repeats the current step, except on the first one.

    On the first step, repeating it would make Hard the same as Again, so Hard is the
    average of the first two steps -- or, with only one step, half as long again (but at
    most a day longer). Anki also rounds a delay longer than a day to whole days; our
    steps are minutes, so that never comes up.
    """
    if step > 0:
        return steps[step]
    first = int(steps[0].total_seconds())
    if len(steps) > 1:
        return timedelta(seconds=(first + int(steps[1].total_seconds())) // 2)
    return timedelta(seconds=min(first * 3 // 2, first + 86_400))


def _answer_review(card: CardSchedule, rating: Rating, now: datetime) -> CardSchedule:
    if rating is Rating.AGAIN:
        return replace(
            card,
            state=CardState.RELEARNING,
            step=0,
            due_at=now + RELEARNING_STEPS[0],
            interval_days=_failed_interval(card.interval_days),
            ease_factor=max(card.ease_factor + EASE_AGAIN, MINIMUM_EASE),
            lapses=card.lapses + 1,
        )

    hard, good, easy = _passing_intervals(card, now)
    if rating is Rating.HARD:
        eased = replace(card, ease_factor=max(card.ease_factor + EASE_HARD, MINIMUM_EASE))
        return _to_review(eased, hard, now)
    if rating is Rating.GOOD:
        return _to_review(card, good, now)
    return _to_review(replace(card, ease_factor=card.ease_factor + EASE_EASY), easy, now)


def _passing_intervals(card: CardSchedule, now: datetime) -> tuple[int, int, int]:
    """Hard, Good, and Easy for a review card, each at least a day more than the last.

    All three are worked out whichever button was pressed, because each one's minimum
    depends on the one before. The arithmetic is at 32-bit precision, like Anki's: in
    about 1 case in 300, 64-bit floats land on the other side of a .5 and come out a day
    different (at 45 days and 130% ease, Good is 58 in Anki and 59 in plain Python).
    """
    current = _f32(max(card.interval_days, 1))
    late = _f32(_days_overdue(card, now))
    ease = _f32(card.ease_factor / 1000)

    hard = _constrain(_f32(current * _f32(HARD_INTERVAL)), minimum=card.interval_days + 1)
    good = _constrain(_f32(_f32(current + _f32(late / 2)) * ease), minimum=hard + 1)
    easy = _constrain(_f32(_f32(_f32(current + late) * ease) * _f32(EASY_BONUS)), minimum=good + 1)
    return hard, good, easy


def _failed_interval(interval_days: int) -> int:
    """The interval a failed card returns to once it has relearned: 1 day, with Anki's
    defaults, because NEW_INTERVAL is 0."""
    shrunk = _f32(_f32(max(interval_days, 1)) * _f32(NEW_INTERVAL))
    return _constrain(shrunk, minimum=MINIMUM_INTERVAL_DAYS)


def _to_review(card: CardSchedule, days: int, now: datetime) -> CardSchedule:
    days = min(max(days, 1), MAXIMUM_INTERVAL_DAYS)
    return replace(
        card, state=CardState.REVIEW, step=0, interval_days=days, due_at=now + timedelta(days=days)
    )


def _days_overdue(card: CardSchedule, now: datetime) -> int:
    """Whole days since the card came due. 0 if it's on time or early."""
    return max(0, (now - card.due_at) // timedelta(days=1))


def _constrain(interval: float, minimum: int) -> int:
    """Round like Anki, then keep the result between `minimum` and the maximum interval.

    The minimum itself is capped too, so at the very top Hard, Good, and Easy can all be
    MAXIMUM_INTERVAL_DAYS.
    """
    minimum = min(max(minimum, 1), MAXIMUM_INTERVAL_DAYS)
    return min(max(_round_half_up(interval), minimum), MAXIMUM_INTERVAL_DAYS)


def _round_half_up(value: float) -> int:
    """Anki rounds halves up. Python's round() rounds them to even: round(32.5) == 32."""
    return math.floor(value + 0.5)


def _f32(value: float) -> float:
    """`value` at 32-bit float precision, which is what Anki's scheduler computes in."""
    return struct.unpack("f", struct.pack("f", value))[0]
