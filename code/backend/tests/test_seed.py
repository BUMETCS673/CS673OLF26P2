"""Tests for the demo data (Iteration 2, B1).

    flask seed [--reset]
    flask time-travel --days N [--email ...]

The acceptance examples are the ones under B1 in code/plans/FINALIZE_ITERATION_2_PLAN.md.
Each command runs through Flask's CLI runner, the same way as typing it in a terminal.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Unit test creation
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

from datetime import timedelta

import pytest

from app.models import Card, Deck, User, utcnow
from app.seed import DEMO_EMAIL

MINUTE, HOUR, DAY = timedelta(minutes=1), timedelta(hours=1), timedelta(days=1)

# Travel Spanish, as the plan's table lists it, in the order the cards are created:
# (front, back, state, due relative to seeding, interval_days, ease_factor, step, lapses)
TRAVEL_SPANISH = [
    ("the airport", "el aeropuerto", "review", -4 * DAY, 10, 2500, 0, 0),
    ("the train station", "la estación de tren", "review", -DAY, 4, 2500, 0, 0),
    ("the beach", "la playa", "review", -HOUR, 1, 2500, 0, 0),
    ("the passport", "el pasaporte", "relearning", -5 * MINUTE, 1, 2300, 0, 1),
    ("the suitcase", "la maleta", "learning", -2 * MINUTE, 0, 2500, 1, 0),
    ("the ticket", "el boleto", "learning", 8 * MINUTE, 0, 2500, 1, 0),
    ("the hotel", "el hotel", "review", 5 * DAY, 12, 2500, 0, 0),
    ("the map", "el mapa", "review", 30 * DAY, 40, 2500, 0, 0),
    ("goodbye", "adiós", "new", None, 0, 2500, 0, 0),
    ("the library", "la biblioteca", "new", None, 0, 2500, 0, 0),
    ("the song", "la canción", "new", None, 0, 2500, 0, 0),
]


@pytest.fixture
def run(app):
    """Run a `flask` command and return Click's result."""
    runner = app.test_cli_runner()
    return lambda *args: runner.invoke(args=list(args))


def _seed(run):
    """Seed, and return the clock just before and just after (to bound the seed's `now`)
    and what the command printed."""
    before = utcnow()
    result = run("seed")
    after = utcnow()
    assert result.exit_code == 0, result.output
    return before, after, result.output


def _assert_ids_printed(output):
    """The seed names each deck's id: they're only 1 and 2 on a fresh database."""
    spanish, travel = _demo_decks()
    assert f"'Spanish 101' (id {spanish.id}, 4 cards)" in output
    assert f"'Travel Spanish' (id {travel.id}, {len(TRAVEL_SPANISH)} cards)" in output


def _demo_user():
    return User.query.filter_by(email=DEMO_EMAIL).one()


def _demo_decks():
    return Deck.query.filter_by(user_id=_demo_user().id).order_by(Deck.id).all()


def _cards(deck):
    return Card.query.filter_by(deck_id=deck.id).order_by(Card.id).all()


def _everything(db):
    """Every user, deck, and card, read fresh from the database."""
    db.session.expire_all()
    return (
        [(u.id, u.email) for u in User.query.order_by(User.id)],
        [(d.id, d.user_id, d.name) for d in Deck.query.order_by(Deck.id)],
        [(c.id, c.deck_id, c.front, c.schedule) for c in Card.query.order_by(Card.id)],
    )


def test_an_empty_database_gets_spanish_101_then_travel_spanish(run):
    # Given an empty database
    # When I run flask seed
    before, after, output = _seed(run)

    # Then the demo user has two decks, Spanish 101 first, and the output names their ids...
    spanish, travel = _demo_decks()
    assert (spanish.name, travel.name) == ("Spanish 101", "Travel Spanish")
    assert travel.description == "English → Spanish, with cards at every stage"
    _assert_ids_printed(output)

    # ...with Spanish 101's four new cards, unchanged since Iteration 1...
    assert [(c.front, c.back, c.state, c.due_at) for c in _cards(spanish)] == [
        ("la biblioteca", "the library", "new", None),
        ("el cuaderno", "the notebook", "new", None),
        ("aprender", "to learn", "new", None),
        ("la semana", "the week", "new", None),
    ]

    # ...and Travel Spanish's eleven, each in the state the plan's table gives it.
    cards = _cards(travel)
    assert len(cards) == len(TRAVEL_SPANISH)
    for card, row in zip(cards, TRAVEL_SPANISH, strict=True):
        front, back, state, due_in, interval_days, ease_factor, step, lapses = row
        schedule = card.schedule
        assert (card.front, card.back, schedule.state) == (front, back, state)
        assert (schedule.interval_days, schedule.ease_factor, schedule.step, schedule.lapses) == (
            interval_days, ease_factor, step, lapses,
        ), front
        if due_in is None:
            assert schedule.due_at is None, front
        else:
            assert before + due_in <= schedule.due_at <= after + due_in, front


def test_a_freshly_seeded_travel_spanish_serves_three_cards_from_each_list(
    run, client, login_as
):
    # Given a freshly seeded database
    _seed(run)
    login_as(_demo_user())
    spanish, travel = _demo_decks()

    # When I ask for Travel Spanish's due cards
    due = client.get(f"/api/decks/{travel.id}/due").get_json()

    # Then each list holds three cards, in the order a session serves them
    assert {name: [card["front"] for card in cards] for name, cards in due.items()} == {
        "learning": ["the passport", "the suitcase", "the ticket"],
        "review": ["the airport", "the train station", "the beach"],
        "new": ["goodbye", "the library", "the song"],
    }
    # And Spanish 101 still serves its four new cards, as Lab 3's walk-through expects
    spanish_due = client.get(f"/api/decks/{spanish.id}/due").get_json()
    assert [len(spanish_due[name]) for name in ("learning", "review", "new")] == [0, 0, 4]


def test_seeding_a_seeded_database_again_changes_nothing(run, db):
    # Given a seeded database
    _seed(run)
    seeded = _everything(db)

    # When I run flask seed again
    result = run("seed")

    # Then nothing changes
    assert result.exit_code == 0
    assert "already exists" in result.output
    assert _everything(db) == seeded


def test_reset_puts_a_reviewed_card_back_and_keeps_one_demo_user(run, db, client, login_as):
    # Given a seeded database where a card has been reviewed
    _seed(run)
    login_as(_demo_user())
    passport = Card.query.filter_by(front="the passport").one()
    assert client.post(f"/api/cards/{passport.id}/review", json={"rating": "good"}).status_code == 200
    db.session.expire_all()
    assert Card.query.filter_by(front="the passport").one().state == "review"

    # When I run flask seed --reset
    before = utcnow()
    result = run("seed", "--reset")
    after = utcnow()

    # Then that card is back in its seeded state...
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Reset")
    db.session.expire_all()
    passport = Card.query.filter_by(front="the passport").one().schedule
    assert (passport.state, passport.interval_days, passport.lapses) == ("relearning", 1, 1)
    assert before - 5 * MINUTE <= passport.due_at <= after - 5 * MINUTE

    # ...and there's still exactly one demo user, with two decks and nothing left over
    assert User.query.filter_by(email=DEMO_EMAIL).count() == 1
    assert [deck.name for deck in _demo_decks()] == ["Spanish 101", "Travel Spanish"]
    assert Deck.query.count() == 2
    assert Card.query.count() == 4 + len(TRAVEL_SPANISH)

    # And the output names the new decks' ids. On Postgres they're never the old ones, and
    # the walkthrough needs them after a reset.
    _assert_ids_printed(result.output)


def test_time_travel_moves_only_the_demo_users_due_times_one_day_earlier(
    run, db, make_user, make_deck, make_card
):
    # Given a seeded database and a second user with a scheduled card
    _seed(run)
    theirs = make_card(
        make_deck(make_user(email="b@example.com")),
        state="review",
        due_at=utcnow() + 3 * DAY,
        interval_days=3,
    )
    before = {card.id: card.schedule.due_at for card in Card.query.all()}

    # When I run flask time-travel --days 1
    result = run("time-travel", "--days", "1")

    # Then every non-null due time of the demo user's is exactly one day earlier, and new
    # cards and the other user's card are unchanged
    assert result.exit_code == 0, result.output
    assert "Moved 8 of demo@cadence.local's cards 1 day(s) earlier." in result.output
    db.session.expire_all()
    for card in Card.query.all():
        was, now = before[card.id], card.schedule.due_at
        if was is None or card.id == theirs.id:
            assert now == was, card.front
        else:
            assert now == was - DAY, card.front


def test_time_travel_for_an_email_nobody_has_says_so(run):
    _seed(run)

    result = run("time-travel", "--days", "1", "--email", "nobody@example.com")

    assert result.exit_code != 0
    assert "No user with the email nobody@example.com" in result.output


def test_time_travel_needs_at_least_one_day(run):
    result = run("time-travel", "--days", "0")

    assert result.exit_code == 2  # Click's usage error; nothing ran
