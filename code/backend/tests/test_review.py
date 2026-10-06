"""Tests for saving a review (Lab 3, Story 5).

    POST /api/cards/<id>/review   {"rating": "again" | "hard" | "good" | "easy"}

The four acceptance tests on the Jira story (SCRUM-74) are the tests marked AT1-AT4,
with their Given / When / Then as comments. The rest cover the technical cases in
code/plans/LAB_3_PLAN.md, Story 5.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   API test creation, including the Jira acceptance tests AT1-AT4
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Card, utcnow
from app.scheduler import CardSchedule, CardState, Rating


def _login(make_user, login_as, email="a@example.com"):
    user = make_user(email=email)
    login_as(user)
    return user


def _review(client, card_id, rating="good"):
    return client.post(f"/api/cards/{card_id}/review", json={"rating": rating})


def _due(res):
    """The `due_at` in a response, as a datetime."""
    return datetime.fromisoformat(res.get_json()["due_at"])


# ---- who can rate what ----------------------------------------------------


def test_rating_a_card_requires_login(client):
    res = _review(client, 1)

    assert res.status_code == 401


def test_another_learners_card_cant_be_rated(
    client, db, make_user, login_as, make_deck, make_card
):  # AT4
    # Given a card in a deck that belongs to a different learner
    _login(make_user, login_as)
    theirs = make_card(make_deck(make_user(email="b@example.com")))

    # When I try to rate it
    res = _review(client, theirs.id)

    # Then the platform responds as though the card does not exist...
    assert res.status_code == 404
    assert res.get_json()["error"]["message"] == "Card not found"
    # ...and leaves the card unchanged
    db.session.expire_all()
    assert db.session.get(Card, theirs.id).state == "new"


def test_rating_a_card_that_doesnt_exist(client, make_user, login_as):
    _login(make_user, login_as)

    res = _review(client, 999)

    assert res.status_code == 404
    assert res.get_json()["error"]["message"] == "Card not found"


# ---- what a rating has to look like ----------------------------------------


def test_a_body_that_isnt_json_is_rejected(client, make_user, login_as, make_deck, make_card):
    card = make_card(make_deck(_login(make_user, login_as)))

    res = client.post(f"/api/cards/{card.id}/review", data="not json")

    assert res.status_code == 400


@pytest.mark.parametrize(
    "body",
    [{}, {"rating": "great"}, {"rating": 3}],
    ids=["missing", "unknown-word", "a-number"],
)
def test_only_the_four_ratings_are_accepted(
    body, client, db, make_user, login_as, make_deck, make_card
):  # AT3
    # Given a card that is due for review
    card = make_card(make_deck(_login(make_user, login_as)))

    # When a rating other than Again, Hard, Good, or Easy is submitted
    res = client.post(f"/api/cards/{card.id}/review", json=body)

    # Then the platform rejects it, saying the rating is invalid...
    assert res.status_code == 422
    assert res.get_json()["error"]["field"] == "rating"
    # ...and leaves the card unchanged
    db.session.expire_all()
    assert db.session.get(Card, card.id).state == "new"


# ---- when a card can be rated ----------------------------------------------


def test_a_review_card_cant_be_rated_before_its_due(
    client, db, make_user, login_as, make_deck, make_card
):
    due = utcnow() + timedelta(days=1)
    card = make_card(
        make_deck(_login(make_user, login_as)), state="review", due_at=due, interval_days=10
    )

    res = _review(client, card.id)

    assert res.status_code == 409
    db.session.expire_all()
    unchanged = db.session.get(Card, card.id).schedule
    assert (unchanged.due_at, unchanged.interval_days) == (due, 10)


@pytest.mark.parametrize(
    ("due_in_minutes", "status"),
    [(30, 409), (10, 200)],
    ids=["due-in-30-min-refused", "due-in-10-min-allowed"],
)
def test_a_learning_card_can_be_rated_up_to_20_minutes_early(
    due_in_minutes, status, client, make_user, login_as, make_deck, make_card
):
    card = make_card(
        make_deck(_login(make_user, login_as)),
        state="learning",
        due_at=utcnow() + timedelta(minutes=due_in_minutes),
        step=1,
    )

    res = _review(client, card.id)

    assert res.status_code == status


# ---- what gets saved -------------------------------------------------------


def test_the_schedulers_answer_is_saved(
    client, make_user, login_as, make_deck, make_card, monkeypatch
):
    # Given my new card, and a stand-in scheduler with a known answer
    deck = make_deck(_login(make_user, login_as))
    card = make_card(deck)
    decided = CardSchedule(
        CardState.LEARNING, datetime(2026, 10, 1, 14, 10, tzinfo=UTC), 0, 2500, 1, 0
    )
    calls = []

    def fake_answer_card(schedule, rating, now):
        calls.append((schedule, rating, now))
        return decided

    monkeypatch.setattr("app.api.cards.answer_card", fake_answer_card)

    # When I rate it Good
    res = _review(client, card.id, "good")

    # Then the right things went in, and what came back was saved
    assert res.status_code == 200
    [(schedule, rating, now)] = calls
    assert schedule.state is CardState.NEW
    assert rating is Rating.GOOD
    assert now.tzinfo is not None
    [saved] = client.get(f"/api/decks/{deck.id}/cards").get_json()
    assert (saved["state"], saved["due_at"]) == ("learning", "2026-10-01T14:10:00Z")


def test_rating_a_new_card_good_saves_it_as_learning(
    client, make_user, login_as, make_deck, make_card
):  # AT1
    # Given a card the learner has never studied
    deck = make_deck(_login(make_user, login_as))
    card = make_card(deck)

    # When the learner rates it Good
    before = utcnow()
    res = _review(client, card.id, "good")
    after = utcnow()

    # Then the platform saves the card as due again in 10 minutes...
    assert res.status_code == 200
    assert res.get_json()["state"] == "learning"
    assert before + timedelta(minutes=10) <= _due(res) <= after + timedelta(minutes=10)
    # ...and still shows that due time after the learner reloads the deck
    [saved] = client.get(f"/api/decks/{deck.id}/cards").get_json()
    assert (saved["state"], saved["due_at"]) == ("learning", res.get_json()["due_at"])


def test_good_on_a_10_day_card_schedules_it_25_days_out(
    client, db, make_user, login_as, make_deck, make_card
):
    card = make_card(
        make_deck(_login(make_user, login_as)), state="review", due_at=utcnow(), interval_days=10
    )

    before = utcnow()
    res = _review(client, card.id, "good")
    after = utcnow()

    assert res.status_code == 200
    assert res.get_json()["state"] == "review"
    assert before + timedelta(days=25) <= _due(res) <= after + timedelta(days=25)
    assert db.session.get(Card, card.id).interval_days == 25


def test_a_second_rating_before_the_card_is_due_is_refused(
    client, make_user, login_as, make_deck, make_card
):  # AT2
    # Given the learner has just rated a card with a 10-day interval Good,
    # so it is next due in 25 days
    deck = make_deck(_login(make_user, login_as))
    card = make_card(deck, state="review", due_at=utcnow(), interval_days=10)
    first = _review(client, card.id, "good")
    assert first.status_code == 200

    # When a second Good rating arrives for the same card, such as from a double-click
    second = _review(client, card.id, "good")

    # Then the platform refuses the second rating and keeps the card due in 25 days
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "conflict"
    [saved] = client.get(f"/api/decks/{deck.id}/cards").get_json()
    assert saved["due_at"] == first.get_json()["due_at"]
