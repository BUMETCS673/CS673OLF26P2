"""WS0's own tests: the health check, the error shape, and the three models.

WS1 and WS2 test their endpoints in test_auth.py, test_decks.py, and test_cards.py.
"""

import json

import pytest
from flask import jsonify

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


def test_a_wrong_method_keeps_the_allow_header(client):
    """RFC 9110 requires Allow on a 405. Swapping in a JSON body must not drop the
    headers Werkzeug set on the original error."""
    response = client.delete("/api/health")

    assert response.status_code == 405
    assert response.get_json()["error"]["code"] == "method_not_allowed"
    assert "GET" in response.headers["Allow"]


def test_a_body_without_a_json_content_type_stays_on_contract(app):
    """A bare `request.get_json()` raises 415, whose code isn't in the contract.

    Endpoints should use `json_object()`, but the handler has to hold the line for
    any that forget -- every error we emit uses a code from the contract's table.
    """
    from flask import request

    @app.route("/api/_bare_get_json", methods=["POST"])
    def _bare_get_json():
        request.get_json()
        return "", 204

    response = app.test_client().post("/api/_bare_get_json", data='{"name": "x"}')

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "bad_request"


def test_an_oversized_body_stays_on_contract(app):
    """MAX_CONTENT_LENGTH makes Werkzeug raise 413, which isn't a contract code.

    Setting the cap without mapping the status would put `{"code": "error"}` back in
    the API -- the thing the closed errors table exists to prevent.
    """
    app.config["MAX_CONTENT_LENGTH"] = 1024

    from app.errors import json_object

    @app.route("/api/_takes_a_body", methods=["POST"])
    def _takes_a_body():
        json_object()  # the cap is enforced when the body is read, not before
        return "", 204

    response = app.test_client().post("/api/_takes_a_body", json={"padding": "p" * 4096})

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "bad_request"
    # Pin the path: json_object()'s own 400 would say "must be a JSON object", so this
    # asserts the size cap answered, not the parse check downstream of it.
    assert body["error"]["message"] == "Request body is too large."


def test_json_object_rejects_a_body_that_isnt_an_object(app):
    from app.errors import json_object

    @app.route("/api/_json_object", methods=["POST"])
    def _json_object_route():
        json_object()
        return "", 204

    client = app.test_client()

    assert client.post("/api/_json_object", json=["not", "an", "object"]).status_code == 400
    assert client.post("/api/_json_object", data="not json").status_code == 400
    assert client.post("/api/_json_object", json={"ok": True}).status_code == 204


def test_json_keys_keep_contract_order(app):
    """Flask 3 reads this off `app.json`; a JSON_SORT_KEYS entry in config is ignored,
    which is why the fields used to come back alphabetized."""
    assert app.json.sort_keys is False

    with app.test_request_context():
        response = jsonify({"id": 1, "email": "a@b.com", "display_name": None, "created_at": "now"})

    assert list(json.loads(response.get_data(as_text=True))) == [
        "id",
        "email",
        "display_name",
        "created_at",
    ]


def test_password_is_hashed_and_never_serialized(make_user):
    user = make_user(email="Miles@BU.edu", password="password123")

    assert user.password_hash != "password123"
    assert user.check_password("password123")
    assert not user.check_password("wrong")
    assert "password" not in user.to_dict()
    assert "password_hash" not in user.to_dict()


def test_the_model_lowercases_and_trims_the_email(db):
    """Assigned straight onto the model, not through `make_user` -- otherwise this
    passes on the fixture's normalization and says nothing about the model."""
    user = User(email="  Miles@BU.edu  ", password_hash="x")
    db.session.add(user)
    db.session.commit()

    assert user.email == "miles@bu.edu"
    assert User.query.filter_by(email="miles@bu.edu").first() is user


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


def test_card_count_does_not_query_per_deck(db, make_user, make_deck):
    """GET /api/decks must stay one query however many decks you own.

    `card_count` is a SQL count on the deck query. Going back to `len(self.cards)`
    would load every card of every deck to count them, and this test would see the
    extra SELECTs.
    """
    from sqlalchemy import event

    user = make_user()
    for i in range(5):
        make_deck(user, name=f"Deck {i}", cards=[("front", "back"), ("a", "b")])
    db.session.expire_all()

    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    decks = Deck.query.filter_by(user_id=user.id).all()
    event.listen(db.engine, "before_cursor_execute", record)
    try:
        payloads = [deck.to_dict() for deck in decks]
    finally:
        event.remove(db.engine, "before_cursor_execute", record)

    assert len(payloads) == 5
    assert [p["card_count"] for p in payloads] == [2, 2, 2, 2, 2]
    assert statements == [], f"card_count fired {len(statements)} extra queries"


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
