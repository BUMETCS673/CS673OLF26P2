"""Tests for the scheduling fields on cards (Lab 3, Step 0a).

What's here is the plumbing the study stories build on: the six new columns and their
defaults, the two that appear in the card JSON, `Card.schedule`, and `as_utc()`. The
scheduling rules themselves are Story 1's, in test_scheduler.py.
"""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.models import Card, as_utc
from app.scheduler import CardSchedule, CardState, Rating


def _login(make_user, login_as):
    user = make_user()
    login_as(user)
    return user


# ---- defaults ------------------------------------------------------------


def test_a_card_created_through_the_api_starts_new(client, db, make_user, login_as, make_deck):
    deck = make_deck(_login(make_user, login_as))

    res = client.post(f"/api/decks/{deck.id}/cards", json={"front": "hola", "back": "hello"})

    assert res.status_code == 201
    body = res.get_json()
    assert body["state"] == "new"
    assert body["due_at"] is None

    card = db.session.get(Card, body["id"])
    assert (card.interval_days, card.ease_factor, card.step, card.lapses) == (0, 2500, 0, 0)


# ---- JSON ----------------------------------------------------------------


def test_card_json_shows_state_and_due_at(client, make_user, login_as, make_deck, make_card):
    deck = make_deck(_login(make_user, login_as))
    make_card(deck, state="learning", due_at=datetime(2026, 10, 1, 14, 10, tzinfo=UTC), step=1)

    [card] = client.get(f"/api/decks/{deck.id}/cards").get_json()

    assert card["state"] == "learning"
    assert card["due_at"] == "2026-10-01T14:10:00Z"


def test_card_json_keeps_the_other_scheduling_fields_internal(make_user, make_deck, make_card):
    card = make_card(make_deck(make_user()), state="review", interval_days=10, lapses=2)

    payload = card.to_dict()

    assert not {"interval_days", "ease_factor", "step", "lapses"} & set(payload)


# ---- Card.schedule -------------------------------------------------------


def test_schedule_round_trips_through_the_database(db, make_user, make_deck, make_card):
    card = make_card(make_deck(make_user()))
    written = CardSchedule(
        state=CardState.REVIEW,
        due_at=datetime(2026, 10, 26, 14, 0, tzinfo=UTC),
        interval_days=25,
        ease_factor=2300,
        step=0,
        lapses=1,
    )

    card.schedule = written
    db.session.commit()
    db.session.expire_all()  # make the next read come from the database, not the session

    read = db.session.get(Card, card.id).schedule
    assert read == written
    # SQLite hands timestamps back without a timezone; the scheduler needs them aware.
    assert read.due_at.tzinfo is not None


def test_schedule_state_comes_back_as_a_card_state(make_user, make_deck, make_card):
    card = make_card(make_deck(make_user()), state="relearning")

    assert card.schedule.state is CardState.RELEARNING


def test_setting_a_schedule_with_an_unknown_state_changes_nothing(make_user, make_deck, make_card):
    card = make_card(make_deck(make_user()))
    bogus = CardSchedule(
        state="paused", due_at=None, interval_days=5, ease_factor=2500, step=0, lapses=0
    )

    with pytest.raises(ValueError):
        card.schedule = bogus

    assert card.state == "new"
    assert card.interval_days == 0


# ---- as_utc --------------------------------------------------------------


def test_as_utc_treats_a_naive_datetime_as_utc():
    assert as_utc(datetime(2026, 10, 1, 14, 0)) == datetime(2026, 10, 1, 14, 0, tzinfo=UTC)


def test_as_utc_converts_other_timezones_to_utc():
    eastern = timezone(timedelta(hours=-4))

    result = as_utc(datetime(2026, 10, 1, 10, 0, tzinfo=eastern))

    assert result == datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
    assert result.tzinfo is UTC


def test_as_utc_passes_none_through():
    assert as_utc(None) is None


# ---- the scheduler interface ---------------------------------------------


def test_ratings_parse_from_the_strings_the_api_sends():
    assert Rating("good") is Rating.GOOD
    with pytest.raises(ValueError):
        Rating("great")


def test_card_schedule_is_immutable():
    schedule = CardSchedule(CardState.NEW, None, 0, 2500, 0, 0)

    with pytest.raises(FrozenInstanceError):
        schedule.step = 1
