"""GET /api/decks/{id}/due and POST /api/cards/{id}/review."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Card, utcnow
from app.scheduler import NEW_CARDS_PER_SESSION, REVIEWS_PER_SESSION, CardSchedule, CardState


def _error(resp):
    return resp.json()["error"]


def _ids(cards):
    return [card["id"] for card in cards]


def _ago(**kwargs):
    return utcnow() - timedelta(**kwargs)


def _from_now(**kwargs):
    return utcnow() + timedelta(**kwargs)


# --- the due list ------------------------------------------------------------------------


async def test_the_due_list_needs_a_signed_in_user(client):
    assert (await client.get("/api/decks/1/due")).status_code == 401


async def test_another_users_deck_is_404(client, me, make_user, make_deck):
    deck = await make_deck(await make_user(email="other@example.com"))

    assert (await client.get(f"/api/decks/{deck.id}/due")).status_code == 404


async def test_an_empty_deck_has_three_empty_lists(client, me, make_deck):
    deck = await make_deck(me)

    resp = await client.get(f"/api/decks/{deck.id}/due")

    assert resp.json() == {"learning": [], "review": [], "new": []}


async def test_each_state_is_grouped_with_relearning_under_learning(
    client, me, make_deck, make_card
):
    deck = await make_deck(me)
    new = await make_card(deck)
    learning = await make_card(deck, state="learning", due_at=_ago(minutes=1))
    review = await make_card(deck, state="review", due_at=_ago(minutes=1))
    relearning = await make_card(deck, state="relearning", due_at=_ago(minutes=2))

    body = (await client.get(f"/api/decks/{deck.id}/due")).json()

    assert _ids(body["new"]) == [new.id]
    assert _ids(body["review"]) == [review.id]
    assert _ids(body["learning"]) == [relearning.id, learning.id]


async def test_reviews_are_most_overdue_first_and_future_ones_are_left_out(
    client, me, make_deck, make_card
):
    deck = await make_deck(me)
    recent = await make_card(deck, state="review", due_at=_ago(hours=1))
    oldest = await make_card(deck, state="review", due_at=_ago(days=3))
    await make_card(deck, state="review", due_at=_from_now(days=1))

    body = (await client.get(f"/api/decks/{deck.id}/due")).json()

    assert _ids(body["review"]) == [oldest.id, recent.id]


async def test_learning_includes_cards_due_soon_but_not_later(client, me, make_deck, make_card):
    deck = await make_deck(me)
    soon = await make_card(deck, state="learning", due_at=_from_now(minutes=5))
    await make_card(deck, state="learning", due_at=_from_now(minutes=30))

    body = (await client.get(f"/api/decks/{deck.id}/due")).json()

    assert _ids(body["learning"]) == [soon.id]


async def test_new_and_review_stop_at_the_session_limits(client, session, me, make_deck):
    deck = await make_deck(me)
    session.add_all(
        Card(deck_id=deck.id, front="Q", back="A") for _ in range(NEW_CARDS_PER_SESSION + 5)
    )
    session.add_all(
        Card(deck_id=deck.id, front="Q", back="A", state="review", due_at=_ago(minutes=1))
        for _ in range(REVIEWS_PER_SESSION + 5)
    )
    await session.commit()

    body = (await client.get(f"/api/decks/{deck.id}/due")).json()

    assert len(body["new"]) == NEW_CARDS_PER_SESSION
    assert len(body["review"]) == REVIEWS_PER_SESSION
    assert _ids(body["new"]) == sorted(_ids(body["new"]))


async def test_due_cards_carry_every_field_and_their_intervals(client, me, make_deck, make_card):
    deck = await make_deck(me)
    await make_card(deck)

    [card] = (await client.get(f"/api/decks/{deck.id}/due")).json()["new"]

    assert (card["state"], card["due_at"], card["origin"]) == ("new", None, "manual")
    assert set(card["intervals"]) == {"again", "hard", "good", "easy"}
    assert all(isinstance(seconds, int) for seconds in card["intervals"].values())


async def test_previews_save_nothing(client, session, me, make_deck, make_card):
    deck = await make_deck(me)
    card = await make_card(deck)

    await client.get(f"/api/decks/{deck.id}/due")

    session.expunge_all()
    saved = await session.scalar(select(Card).where(Card.id == card.id))
    assert (saved.state, saved.due_at) == ("new", None)


async def test_the_card_list_has_no_intervals(client, me, make_deck, make_card):
    deck = await make_deck(me)
    await make_card(deck)

    [card] = (await client.get(f"/api/decks/{deck.id}/cards")).json()

    assert "intervals" not in card


# --- reviewing a card --------------------------------------------------------------------


def _rate(client, card_id, rating="good"):
    return client.post(f"/api/cards/{card_id}/review", json={"rating": rating})


async def test_reviewing_needs_a_signed_in_user(client):
    assert (await _rate(client, 1)).status_code == 401


async def test_another_users_card_is_404(client, me, make_user, make_deck, make_card):
    card = await make_card(await make_deck(await make_user(email="other@example.com")))

    resp = await _rate(client, card.id)

    assert resp.status_code == 404
    assert _error(resp)["message"] == "Card not found"


async def test_a_missing_card_is_404(client, me):
    assert (await _rate(client, 999)).status_code == 404


@pytest.mark.parametrize("rating", ["perfect", "GOOD", "", None, 3])
async def test_only_the_four_ratings_are_accepted(client, me, make_deck, make_card, rating):
    card = await make_card(await make_deck(me))

    resp = await _rate(client, card.id, rating)

    assert resp.status_code == 422
    assert _error(resp) == {
        "code": "validation_error",
        "message": "rating must be one of: again, hard, good, easy",
        "field": "rating",
    }


async def test_rating_a_new_card_good_saves_it_as_learning(
    client, session, me, make_deck, make_card
):
    card = await make_card(await make_deck(me))

    resp = await _rate(client, card.id)

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "learning"
    assert datetime.fromisoformat(body["due_at"]) > utcnow()
    assert set(body["intervals"]) == {"again", "hard", "good", "easy"}
    session.expunge_all()
    saved = await session.scalar(select(Card).where(Card.id == card.id))
    assert saved.state == "learning"


async def test_good_on_a_10_day_card_schedules_it_25_days_out(
    client, me, make_deck, make_card
):
    card = await make_card(
        await make_deck(me), state="review", due_at=_ago(minutes=1), interval_days=10
    )

    body = (await _rate(client, card.id)).json()

    delay = datetime.fromisoformat(body["due_at"]) - utcnow()
    assert timedelta(days=24, hours=23) < delay <= timedelta(days=25)


async def test_a_review_card_cant_be_rated_before_its_due(client, me, make_deck, make_card):
    card = await make_card(await make_deck(me), state="review", due_at=_from_now(days=1))

    resp = await _rate(client, card.id)

    assert resp.status_code == 409
    assert _error(resp)["message"] == "Card isn't due yet"


@pytest.mark.parametrize(("minutes", "status"), [(19, 200), (21, 409)])
async def test_a_learning_card_can_be_rated_up_to_20_minutes_early(
    client, me, make_deck, make_card, minutes, status
):
    card = await make_card(
        await make_deck(me), state="learning", due_at=_from_now(minutes=minutes)
    )

    assert (await _rate(client, card.id)).status_code == status


# --- the schedule on a card --------------------------------------------------------------


async def test_a_schedule_round_trips_through_the_database(
    client, session, me, make_deck, make_card
):
    card = await make_card(await make_deck(me))
    due = _from_now(days=3)

    card.schedule = CardSchedule(
        state=CardState.REVIEW, due_at=due, interval_days=3, ease_factor=2600, step=0, lapses=1
    )
    await session.commit()
    session.expunge_all()
    saved = await session.scalar(select(Card).where(Card.id == card.id))

    assert saved.schedule == card.schedule
    assert saved.schedule.state is CardState.REVIEW


async def test_an_unknown_state_changes_nothing(me, make_deck, make_card):
    card = await make_card(await make_deck(me))
    bad = CardSchedule(
        state="retired", due_at=None, interval_days=9, ease_factor=2500, step=0, lapses=0
    )

    with pytest.raises(ValueError):
        card.schedule = bad

    assert (card.state, card.interval_days) == ("new", 0)


def test_a_card_schedule_is_immutable():
    schedule = CardSchedule(
        state=CardState.NEW, due_at=None, interval_days=0, ease_factor=2500, step=0, lapses=0
    )

    with pytest.raises(FrozenInstanceError):
        schedule.step = 1
