"""Interval previews on study cards (Iteration 2, chunk B3).

Each rating button shows when the card would be due again if the learner pressed it.
The backend works these out with the real scheduler and sends them as `intervals`:

    "intervals": {"again": 60, "hard": 600, "good": 86400, "easy": 345600}

The numbers below are the reference table in
code/plans/FINALIZE_ITERATION_2_PLAN.md ("Study cards gain `intervals` (B3)").
"""

# AI Utilization: 90%
# AI Tools Used: Claude
# AI-Assisted Activities:
#   - Unit test creation (from the plan's acceptance examples)
# Reviewed, run, and checked against the plan's reference table by Von.

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Card
from app.scheduler import CardSchedule, CardState, Rating, preview_intervals

NOW = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
DAY = 86_400

# (description, schedule at NOW, expected intervals in seconds)
REFERENCE = [
    (
        "new",
        CardSchedule(CardState.NEW, None, 0, 2500, 0, 0),
        {"again": 60, "hard": 330, "good": 600, "easy": 4 * DAY},
    ),
    (
        "learning on step 0",
        CardSchedule(CardState.LEARNING, NOW, 0, 2500, 0, 0),
        {"again": 60, "hard": 330, "good": 600, "easy": 4 * DAY},
    ),
    (
        "learning on step 1",
        CardSchedule(CardState.LEARNING, NOW, 0, 2500, 1, 0),
        {"again": 60, "hard": 600, "good": DAY, "easy": 4 * DAY},
    ),
    (
        "relearning, interval 1",
        CardSchedule(CardState.RELEARNING, NOW, 1, 2300, 0, 1),
        {"again": 600, "hard": 900, "good": DAY, "easy": 2 * DAY},
    ),
    (
        "review, I = 10, 250%, on time",
        CardSchedule(CardState.REVIEW, NOW, 10, 2500, 0, 0),
        {"again": 600, "hard": 12 * DAY, "good": 25 * DAY, "easy": 33 * DAY},
    ),
    (
        "review, I = 10, 250%, 4 days overdue",
        CardSchedule(CardState.REVIEW, NOW - timedelta(days=4), 10, 2500, 0, 0),
        {"again": 600, "hard": 12 * DAY, "good": 30 * DAY, "easy": 46 * DAY},
    ),
]


def _login(make_user, login_as, email="a@example.com"):
    user = make_user(email=email)
    login_as(user)
    return user


def _freeze(monkeypatch, *modules):
    """Make the endpoints read NOW from the clock, so the numbers are exact."""
    for module in modules:
        monkeypatch.setattr(f"{module}.utcnow", lambda: NOW)


def _make(make_card, deck, schedule, front):
    return make_card(
        deck,
        front=front,
        state=schedule.state.value,
        due_at=schedule.due_at,
        interval_days=schedule.interval_days,
        ease_factor=schedule.ease_factor,
        step=schedule.step,
        lapses=schedule.lapses,
    )


# ---- the scheduler ---------------------------------------------------------


@pytest.mark.parametrize(
    ("schedule", "expected"),
    [(schedule, expected) for _, schedule, expected in REFERENCE],
    ids=[name for name, _, _ in REFERENCE],
)
def test_preview_intervals_match_the_reference_table(schedule, expected):
    # Given a card from the reference table / When we preview it at NOW
    previews = preview_intervals(schedule, NOW)

    # Then every rating has the table's interval, as a timedelta
    assert previews == {Rating(r): timedelta(seconds=s) for r, s in expected.items()}


def test_preview_intervals_is_keyed_by_every_rating():
    previews = preview_intervals(REFERENCE[0][1], NOW)
    assert list(previews) == list(Rating)


# ---- GET /api/decks/:id/due -------------------------------------------------


def test_due_cards_carry_the_reference_intervals(
    client, make_user, login_as, make_deck, make_card, monkeypatch
):
    # Given the reference cards, all due, in my deck
    deck = make_deck(_login(make_user, login_as))
    expected = {}
    for name, schedule, intervals in REFERENCE:
        card = _make(make_card, deck, schedule, front=name)
        expected[card.id] = intervals
    _freeze(monkeypatch, "app.api.decks")

    # When I ask for the deck's due cards
    res = client.get(f"/api/decks/{deck.id}/due")

    # Then every card, in every list, has its row's intervals in whole seconds
    assert res.status_code == 200
    body = res.get_json()
    served = body["learning"] + body["review"] + body["new"]
    assert {c["id"] for c in served} == set(expected)
    for card in served:
        assert card["intervals"] == expected[card["id"]], card["front"]
        assert all(type(v) is int for v in card["intervals"].values())


def test_due_cards_still_have_every_card_field(client, make_user, login_as, make_deck, make_card):
    deck = make_deck(_login(make_user, login_as))
    make_card(deck)

    [card] = client.get(f"/api/decks/{deck.id}/due").get_json()["new"]

    assert set(card) == {
        "id",
        "deck_id",
        "front",
        "back",
        "state",
        "due_at",
        "created_at",
        "updated_at",
        "intervals",
    }


def test_previews_save_nothing(client, make_user, login_as, make_deck, make_card, db):
    # Given a learning card
    deck = make_deck(_login(make_user, login_as))
    due = datetime(2026, 10, 1, 13, 58, tzinfo=UTC)
    card = make_card(deck, state="learning", due_at=due, step=1)
    before = (
        card.state,
        card.due_at,
        card.interval_days,
        card.ease_factor,
        card.step,
        card.lapses,
        card.updated_at,
    )

    # When its previews are worked out
    assert client.get(f"/api/decks/{deck.id}/due").status_code == 200

    # Then its row in the database is unchanged
    db.session.expire_all()
    row = db.session.get(Card, card.id)
    assert (
        row.state,
        row.due_at,
        row.interval_days,
        row.ease_factor,
        row.step,
        row.lapses,
        row.updated_at,
    ) == before


# ---- POST /api/cards/:id/review -----------------------------------------------


def test_review_response_previews_the_next_answer(
    client, make_user, login_as, make_deck, make_card, monkeypatch
):
    # Given a new card
    deck = make_deck(_login(make_user, login_as))
    card = make_card(deck)
    _freeze(monkeypatch, "app.api.cards")

    # When I rate it Good
    res = client.post(f"/api/cards/{card.id}/review", json={"rating": "good"})

    # Then it's learning, and its intervals are the "learning on step 1" row
    assert res.status_code == 200
    body = res.get_json()
    assert body["state"] == "learning"
    assert body["intervals"] == {"again": 60, "hard": 600, "good": DAY, "easy": 4 * DAY}


# ---- nowhere else -------------------------------------------------------------


def test_card_list_and_card_edit_have_no_intervals(
    client, make_user, login_as, make_deck, make_card
):
    deck = make_deck(_login(make_user, login_as))
    card = make_card(deck, state="learning", due_at=NOW, step=1)

    listed = client.get(f"/api/decks/{deck.id}/cards").get_json()
    edited = client.patch(f"/api/cards/{card.id}", json={"front": "new front"}).get_json()

    assert all("intervals" not in c for c in listed)
    assert "intervals" not in edited
