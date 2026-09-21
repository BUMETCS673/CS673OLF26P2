"""Tests for the card endpoints (WS2)."""

from app.extensions import db
from app.models import Card


def _login(make_user, login_as, email="a@example.com"):
    user = make_user(email=email)
    login_as(user)
    return user


# ---- auth ----------------------------------------------------------------


def test_every_card_route_requires_login(client):
    assert client.get("/api/decks/1/cards").status_code == 401
    assert (
        client.post("/api/decks/1/cards", json={"front": "q", "back": "a"}).status_code
        == 401
    )
    assert client.patch("/api/cards/1", json={"front": "q"}).status_code == 401
    res = client.delete("/api/cards/1")
    assert res.status_code == 401


# ---- list ----------------------------------------------------------------


def test_list_cards_in_order(client, make_user, login_as, make_deck):
    me = _login(make_user, login_as)
    deck = make_deck(me, cards=[("q1", "a1"), ("q2", "a2")])

    res = client.get(f"/api/decks/{deck.id}/cards")

    assert res.status_code == 200
    data = res.get_json()
    assert [c["front"] for c in data] == ["q1", "q2"]
    assert all(c["deck_id"] == deck.id for c in data)


def test_list_cards_of_empty_deck(client, make_user, login_as, make_deck):
    me = _login(make_user, login_as)
    deck = make_deck(me)
    res = client.get(f"/api/decks/{deck.id}/cards")
    assert res.status_code == 200
    assert res.get_json() == []


def test_list_cards_of_someone_elses_deck_is_404(
    client, make_user, login_as, make_deck
):
    _login(make_user, login_as)
    other = make_user(email="b@example.com")
    theirs = make_deck(other, cards=[("secret", "secret")])

    res = client.get(f"/api/decks/{theirs.id}/cards")

    assert res.status_code == 404


def test_list_cards_of_missing_deck_is_404(client, make_user, login_as):
    _login(make_user, login_as)
    assert client.get("/api/decks/9999/cards").status_code == 404


# ---- create --------------------------------------------------------------


def test_create_card(client, make_user, login_as, make_deck):
    me = _login(make_user, login_as)
    deck = make_deck(me)

    res = client.post(
        f"/api/decks/{deck.id}/cards", json={"front": " hola ", "back": "hello"}
    )

    assert res.status_code == 201
    body = res.get_json()
    assert body["front"] == "hola"
    assert body["back"] == "hello"
    assert body["deck_id"] == deck.id
    assert client.get(f"/api/decks/{deck.id}").get_json()["card_count"] == 1


def test_create_card_requires_front_and_back(client, make_user, login_as, make_deck):
    me = _login(make_user, login_as)
    deck = make_deck(me)
    url = f"/api/decks/{deck.id}/cards"

    res = client.post(url, json={"back": "a"})
    assert res.status_code == 422
    assert res.get_json()["error"]["field"] == "front"

    res = client.post(url, json={"front": "q"})
    assert res.status_code == 422
    assert res.get_json()["error"]["field"] == "back"

    res = client.post(url, json={"front": " ", "back": "a"})
    assert res.status_code == 422
    assert res.get_json()["error"]["field"] == "front"


def test_create_card_text_too_long(client, make_user, login_as, make_deck):
    me = _login(make_user, login_as)
    deck = make_deck(me)
    res = client.post(
        f"/api/decks/{deck.id}/cards", json={"front": "x" * 2001, "back": "a"}
    )
    assert res.status_code == 422
    assert res.get_json()["error"]["field"] == "front"


def test_create_card_without_json_content_type_is_400(
    client, make_user, login_as, make_deck
):
    me = _login(make_user, login_as)
    deck = make_deck(me)
    res = client.post(f"/api/decks/{deck.id}/cards", data="front=q&back=a")
    assert res.status_code == 400


def test_create_card_in_someone_elses_deck_is_404(
    client, make_user, login_as, make_deck
):
    _login(make_user, login_as)
    other = make_user(email="b@example.com")
    theirs = make_deck(other)
    theirs_id = theirs.id

    res = client.post(
        f"/api/decks/{theirs_id}/cards", json={"front": "q", "back": "a"}
    )

    assert res.status_code == 404
    assert Card.query.filter_by(deck_id=theirs_id).count() == 0


# ---- update --------------------------------------------------------------


def test_patch_card_updates_only_given_fields(client, make_user, login_as, make_deck):
    me = _login(make_user, login_as)
    deck = make_deck(me, cards=[("old front", "old back")])
    card = Card.query.filter_by(deck_id=deck.id).first()

    res = client.patch(f"/api/cards/{card.id}", json={"front": "new front"})

    assert res.status_code == 200
    body = res.get_json()
    assert body["front"] == "new front"
    assert body["back"] == "old back"


def test_patch_card_rejects_blank_and_changes_nothing(
    client, make_user, login_as, make_deck
):
    me = _login(make_user, login_as)
    deck = make_deck(me, cards=[("front", "back")])
    card = Card.query.filter_by(deck_id=deck.id).first()

    res = client.patch(f"/api/cards/{card.id}", json={"front": "new", "back": ""})

    assert res.status_code == 422
    assert res.get_json()["error"]["field"] == "back"
    listed = client.get(f"/api/decks/{deck.id}/cards").get_json()
    assert listed[0]["front"] == "front"


def test_patch_someone_elses_card_is_404(client, make_user, login_as, make_deck):
    _login(make_user, login_as)
    other = make_user(email="b@example.com")
    theirs = make_deck(other, cards=[("front", "back")])
    card = Card.query.filter_by(deck_id=theirs.id).first()
    card_id = card.id

    res = client.patch(f"/api/cards/{card_id}", json={"front": "hacked"})

    assert res.status_code == 404
    # Drop the test session's cached copy so we really read from the database.
    db.session.expire_all()
    assert Card.query.get(card_id).front == "front"


def test_patch_missing_card_is_404(client, make_user, login_as):
    _login(make_user, login_as)
    assert client.patch("/api/cards/9999", json={"front": "x"}).status_code == 404


# ---- delete --------------------------------------------------------------


def test_delete_card(client, make_user, login_as, make_deck):
    me = _login(make_user, login_as)
    deck = make_deck(me, cards=[("q1", "a1"), ("q2", "a2")])
    card = Card.query.filter_by(deck_id=deck.id).first()

    res = client.delete(f"/api/cards/{card.id}")

    assert res.status_code == 204
    assert res.data == b""
    remaining = client.get(f"/api/decks/{deck.id}/cards").get_json()
    assert [c["front"] for c in remaining] == ["q2"]


def test_delete_someone_elses_card_is_404(client, make_user, login_as, make_deck):
    _login(make_user, login_as)
    other = make_user(email="b@example.com")
    theirs = make_deck(other, cards=[("front", "back")])
    card_id = Card.query.filter_by(deck_id=theirs.id).first().id

    res = client.delete(f"/api/cards/{card_id}")

    assert res.status_code == 404
    # Ask the database directly (not the cached copy) that the card still exists.
    assert Card.query.filter_by(id=card_id).count() == 1
