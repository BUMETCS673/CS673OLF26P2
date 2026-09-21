"""Tests for the deck endpoints (WS2)."""

from app.models import Card, Deck


def _login(make_user, login_as, email="a@example.com"):
    user = make_user(email=email)
    login_as(user)
    return user


# ---- auth ----------------------------------------------------------------


def test_every_deck_route_requires_login(client):
    assert client.get("/api/decks").status_code == 401
    assert client.post("/api/decks", json={"name": "x"}).status_code == 401
    assert client.get("/api/decks/1").status_code == 401
    assert client.patch("/api/decks/1", json={"name": "x"}).status_code == 401
    res = client.delete("/api/decks/1")
    assert res.status_code == 401


# ---- list ----------------------------------------------------------------


def test_list_returns_only_my_decks(client, make_user, login_as, make_deck):
    me = _login(make_user, login_as)
    other = make_user(email="b@example.com")
    make_deck(me, name="Mine", cards=[("q", "a"), ("q2", "a2")])
    make_deck(other, name="Not mine")

    res = client.get("/api/decks")

    assert res.status_code == 200
    data = res.get_json()
    assert [d["name"] for d in data] == ["Mine"]
    assert data[0]["card_count"] == 2


def test_list_is_empty_for_new_user(client, make_user, login_as):
    _login(make_user, login_as)
    res = client.get("/api/decks")
    assert res.status_code == 200
    assert res.get_json() == []


# ---- create --------------------------------------------------------------


def test_create_deck(client, make_user, login_as):
    _login(make_user, login_as)

    res = client.post(
        "/api/decks", json={"name": "  Biology  ", "description": "Cells"}
    )

    assert res.status_code == 201
    body = res.get_json()
    assert body["name"] == "Biology"
    assert body["description"] == "Cells"
    assert body["card_count"] == 0
    assert isinstance(body["id"], int)


def test_create_deck_without_description(client, make_user, login_as):
    _login(make_user, login_as)
    res = client.post("/api/decks", json={"name": "Biology"})
    assert res.status_code == 201
    assert res.get_json()["description"] is None


def test_create_deck_belongs_to_logged_in_user(client, make_user, login_as):
    me = _login(make_user, login_as)
    res = client.post("/api/decks", json={"name": "Biology"})
    assert Deck.query.get(res.get_json()["id"]).user_id == me.id


def test_create_deck_requires_name(client, make_user, login_as):
    _login(make_user, login_as)

    for body in ({}, {"name": ""}, {"name": "   "}, {"name": 5}):
        res = client.post("/api/decks", json=body)
        assert res.status_code == 422, body
        error = res.get_json()["error"]
        assert error["code"] == "validation_error"
        assert error["field"] == "name"


def test_create_deck_name_too_long(client, make_user, login_as):
    _login(make_user, login_as)
    res = client.post("/api/decks", json={"name": "x" * 121})
    assert res.status_code == 422
    assert res.get_json()["error"]["field"] == "name"


def test_create_deck_description_must_be_string(client, make_user, login_as):
    _login(make_user, login_as)
    res = client.post("/api/decks", json={"name": "ok", "description": 7})
    assert res.status_code == 422
    assert res.get_json()["error"]["field"] == "description"


def test_create_deck_without_json_content_type_is_400(client, make_user, login_as):
    _login(make_user, login_as)
    res = client.post("/api/decks", data="name=x")
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "bad_request"


def test_create_deck_body_must_be_object(client, make_user, login_as):
    _login(make_user, login_as)
    res = client.post("/api/decks", json=["not", "an", "object"])
    assert res.status_code == 400


# ---- get -----------------------------------------------------------------


def test_get_deck(client, make_user, login_as, make_deck):
    me = _login(make_user, login_as)
    deck = make_deck(me, name="Mine", cards=[("q", "a")])

    res = client.get(f"/api/decks/{deck.id}")

    assert res.status_code == 200
    assert res.get_json()["name"] == "Mine"
    assert res.get_json()["card_count"] == 1


def test_get_missing_deck_is_404(client, make_user, login_as):
    _login(make_user, login_as)
    res = client.get("/api/decks/9999")
    assert res.status_code == 404
    assert res.get_json()["error"]["code"] == "not_found"


def test_get_someone_elses_deck_is_404_not_403(
    client, make_user, login_as, make_deck
):
    _login(make_user, login_as)
    other = make_user(email="b@example.com")
    theirs = make_deck(other)

    res = client.get(f"/api/decks/{theirs.id}")

    assert res.status_code == 404


# ---- update --------------------------------------------------------------


def test_patch_updates_only_given_fields(client, make_user, login_as, make_deck):
    me = _login(make_user, login_as)
    deck = make_deck(me, name="Old", description="keep me")

    res = client.patch(f"/api/decks/{deck.id}", json={"name": "New"})

    assert res.status_code == 200
    body = res.get_json()
    assert body["name"] == "New"
    assert body["description"] == "keep me"


def test_patch_can_clear_description(client, make_user, login_as, make_deck):
    me = _login(make_user, login_as)
    deck = make_deck(me, description="something")

    res = client.patch(f"/api/decks/{deck.id}", json={"description": None})

    assert res.status_code == 200
    assert res.get_json()["description"] is None


def test_patch_rejects_blank_name_and_changes_nothing(
    client, make_user, login_as, make_deck
):
    me = _login(make_user, login_as)
    deck = make_deck(me, name="Old", description="old desc")

    res = client.patch(
        f"/api/decks/{deck.id}", json={"name": " ", "description": "new desc"}
    )

    assert res.status_code == 422
    assert res.get_json()["error"]["field"] == "name"
    assert client.get(f"/api/decks/{deck.id}").get_json()["description"] == "old desc"


def test_patch_someone_elses_deck_is_404(client, make_user, login_as, make_deck):
    _login(make_user, login_as)
    other = make_user(email="b@example.com")
    theirs = make_deck(other, name="Theirs")

    res = client.patch(f"/api/decks/{theirs.id}", json={"name": "Hacked"})

    assert res.status_code == 404
    assert Deck.query.get(theirs.id).name == "Theirs"


# ---- delete --------------------------------------------------------------


def test_delete_deck_also_deletes_its_cards(client, make_user, login_as, make_deck):
    me = _login(make_user, login_as)
    deck = make_deck(me, cards=[("q1", "a1"), ("q2", "a2")])
    deck_id = deck.id

    res = client.delete(f"/api/decks/{deck_id}")

    assert res.status_code == 204
    assert res.data == b""
    assert client.get(f"/api/decks/{deck_id}").status_code == 404
    assert Card.query.filter_by(deck_id=deck_id).count() == 0


def test_delete_someone_elses_deck_is_404(client, make_user, login_as, make_deck):
    _login(make_user, login_as)
    other = make_user(email="b@example.com")
    theirs = make_deck(other)
    theirs_id = theirs.id

    res = client.delete(f"/api/decks/{theirs_id}")

    assert res.status_code == 404
    assert Deck.query.get(theirs_id) is not None
