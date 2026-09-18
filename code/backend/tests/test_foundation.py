"""WS0's own tests: the health check, the error shape, and the three models.

WS1 and WS2 test their endpoints in test_auth.py, test_decks.py, and test_cards.py.
"""

import pytest

from app.models import Card, Deck, User


def test_health_returns_ok(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_unknown_route_uses_the_contract_error_shape(client):
    response = client.get("/api/nope")

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"
    assert "message" in response.get_json()["error"]


def test_password_is_hashed_and_never_serialized(make_user):
    user = make_user(email="Miles@BU.edu", password="password123")

    assert user.password_hash != "password123"
    assert user.check_password("password123")
    assert not user.check_password("wrong")
    assert "password" not in user.to_dict()
    assert "password_hash" not in user.to_dict()


def test_email_is_stored_lowercase(make_user):
    user = make_user(email="  Miles@BU.edu  ")

    assert user.email == "miles@bu.edu"


def test_duplicate_email_is_rejected_by_the_database(db, make_user):
    """WS1 turns this IntegrityError into the contract's 409."""
    from sqlalchemy.exc import IntegrityError

    make_user(email="taken@example.com")
    duplicate = User(email="taken@example.com", password_hash="x")
    db.session.add(duplicate)

    with pytest.raises(IntegrityError):
        db.session.commit()

    db.session.rollback()


def test_user_json_matches_the_contract(make_user):
    payload = make_user(email="a@example.com", display_name="Demo User").to_dict()

    assert set(payload) == {"id", "email", "display_name", "created_at"}
    assert payload["created_at"].endswith("Z")


def test_deck_json_includes_card_count(make_user, make_deck):
    user = make_user()
    deck = make_deck(user, cards=[("la biblioteca", "the library"), ("aprender", "to learn")])

    payload = deck.to_dict()

    assert set(payload) == {"id", "name", "description", "card_count", "created_at", "updated_at"}
    assert payload["card_count"] == 2


def test_card_json_matches_the_contract(make_user, make_deck):
    deck = make_deck(make_user(), cards=[("la biblioteca", "the library")])

    payload = deck.cards[0].to_dict()

    assert set(payload) == {"id", "deck_id", "front", "back", "created_at", "updated_at"}
    assert payload["deck_id"] == deck.id


def test_deleting_a_deck_deletes_its_cards(db, make_user, make_deck):
    deck = make_deck(make_user(), cards=[("front", "back"), ("otro", "another")])
    assert Card.query.count() == 2

    db.session.delete(deck)
    db.session.commit()

    assert Card.query.count() == 0


def test_deleting_a_user_deletes_their_decks_and_cards(db, make_user, make_deck):
    user = make_user()
    make_deck(user, cards=[("front", "back")])

    db.session.delete(user)
    db.session.commit()

    assert Deck.query.count() == 0
    assert Card.query.count() == 0


def test_seed_is_safe_to_run_twice(app, db):
    from app.seed import DEMO_EMAIL, seed_command

    runner = app.test_cli_runner()
    runner.invoke(seed_command)
    runner.invoke(seed_command)

    assert User.query.filter_by(email=DEMO_EMAIL).count() == 1
    assert Deck.query.count() == 1
