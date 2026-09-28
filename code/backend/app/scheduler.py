"""Anki's scheduling algorithm: when each card is next due (Lab 3, Story 1).

Step 0a wrote the interface below and Story 1 fills in `answer_card()`. Stories 2 and 5
code against these names too, so they're frozen -- see "The scheduler interface" in
code/plans/LAB_3_PLAN.md before changing any of them.

This module is pure (rule 7 in the plan). It imports nothing from Flask, SQLAlchemy, or
app.models, and it never reads the clock: `now` is always passed in, UTC-aware.
`Card.schedule` converts between a database row and a `CardSchedule`.
"""

from dataclasses import dataclass
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
    """The card's schedule after the learner answers it with `rating` at `now`."""
    raise NotImplementedError("Story 1 -- see code/plans/LAB_3_PLAN.md")
