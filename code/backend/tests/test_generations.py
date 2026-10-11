"""B4's tests for accepting and rejecting AI suggestions: one per acceptance example under
B4 in code/plans/ITERATION_3_PLAN.md, plus the edges of contract C4.

    POST /api/generations/<id>/accept  {"indexes": [...]}  -> 201 {cards, generation}
    POST /api/generations/<id>/reject  {"indexes": [...]}  -> 200 Generation
"""

# AI Utilization: 90%
# AI Tools Used: Claude
# AI-Assisted Activities:
#   - Unit test creation (from the plan's acceptance examples)
# Human role: ran the suite locally and in Docker, and checked each test against the plan,
# by Osasenaga Von Okunbor.

import pytest

from app.models import AiGeneration, Card


def _login(make_user, login_as, email="a@example.com"):
    user = make_user(email=email)
    login_as(user)
    return user


@pytest.fixture
def make_generation(db):
    def _make_generation(user, deck, count=3):
        generation = AiGeneration(
            user_id=user.id,
            deck_id=deck.id,
            mode="prompt",
            prompt="Spanish travel words",
            requested_count=count,
            model="fake",
            candidates=[
                {"front": f"q{i}", "back": f"a{i}", "status": "pending"} for i in range(count)
            ],
        )
        db.session.add(generation)
        db.session.commit()
        return generation

    return _make_generation


@pytest.fixture
def mine(client, make_user, login_as, make_deck, make_generation):
    """My deck, with a generation of three pending suggestions in it."""
    me = _login(make_user, login_as)
    deck = make_deck(me)
    return deck, make_generation(me, deck)


def _accept(client, generation_id, indexes):
    return client.post(f"/api/generations/{generation_id}/accept", json={"indexes": indexes})


def _reject(client, generation_id, indexes):
    return client.post(f"/api/generations/{generation_id}/reject", json={"indexes": indexes})


def _statuses(body):
    return [card["status"] for card in body["cards"]]


# ---- who can decide ---------------------------------------------------------


def test_both_routes_require_login(client):
    assert _accept(client, 1, [0]).status_code == 401
    assert _reject(client, 1, [0]).status_code == 401


def test_someone_elses_generation_is_404(client, make_user, login_as, make_deck, make_generation):
    _login(make_user, login_as)
    other = make_user(email="b@example.com")
    theirs = make_generation(other, make_deck(other))

    for res in (_accept(client, theirs.id, [0]), _reject(client, theirs.id, [0])):
        assert res.status_code == 404
        assert res.get_json()["error"]["message"] == "Generation not found."
    assert Card.query.count() == 0


def test_unknown_generation_is_404(client, make_user, login_as):
    _login(make_user, login_as)
    for res in (_accept(client, 9999, [0]), _reject(client, 9999, [0])):
        assert res.status_code == 404
        assert res.get_json()["error"]["message"] == "Generation not found."


def test_ownership_is_checked_before_the_body(
    client, make_user, login_as, make_deck, make_generation
):
    # A stranger with a bad body still gets 404, so they learn nothing from a 422.
    _login(make_user, login_as)
    other = make_user(email="b@example.com")
    theirs = make_generation(other, make_deck(other))
    assert _accept(client, theirs.id, "0").status_code == 404


# ---- accept -----------------------------------------------------------------


def test_accept_creates_cards_in_index_order(client, mine):
    # Given my generation with 3 pending cards / When I accept [2, 0]
    deck, generation = mine
    res = _accept(client, generation.id, [2, 0])

    # Then two cards, in index order, both AI, in the generation's deck
    assert res.status_code == 201
    body = res.get_json()
    assert [c["front"] for c in body["cards"]] == ["q0", "q2"]
    assert all(c["origin"] == "ai" for c in body["cards"])
    assert all(c["deck_id"] == deck.id for c in body["cards"])
    assert _statuses(body["generation"]) == ["accepted", "pending", "accepted"]
    saved = Card.query.filter_by(deck_id=deck.id).all()
    assert all(card.generation_id == generation.id for card in saved)


def test_accepting_again_creates_nothing(client, mine):
    deck, generation = mine
    _accept(client, generation.id, [0, 2])

    res = _accept(client, generation.id, [0])

    assert res.status_code == 201
    assert res.get_json()["cards"] == []
    assert Card.query.filter_by(deck_id=deck.id).count() == 2


def test_repeated_indexes_make_one_card(client, mine):
    deck, generation = mine
    res = _accept(client, generation.id, [0, 0])

    assert len(res.get_json()["cards"]) == 1
    assert Card.query.filter_by(deck_id=deck.id).count() == 1


def test_accepted_cards_are_ai_in_the_deck_list(client, mine):
    deck, generation = mine
    _accept(client, generation.id, [0, 1])

    cards = client.get(f"/api/decks/{deck.id}/cards").get_json()

    assert [c["origin"] for c in cards] == ["ai", "ai"]


def test_accept_is_saved_not_just_cached(client, mine, db):
    # Rule 20: a JSON column changed in place is silently never saved.
    deck, generation = mine
    _accept(client, generation.id, [0])

    db.session.expire_all()

    assert db.session.get(AiGeneration, generation.id).candidates[0]["status"] == "accepted"


# ---- reject -----------------------------------------------------------------


def test_reject_sets_the_status(client, mine, db):
    deck, generation = mine
    res = _reject(client, generation.id, [1])

    assert res.status_code == 200
    assert _statuses(res.get_json()) == ["pending", "rejected", "pending"]
    db.session.expire_all()
    assert db.session.get(AiGeneration, generation.id).candidates[1]["status"] == "rejected"
    assert Card.query.filter_by(deck_id=deck.id).count() == 0


def test_a_rejected_card_cannot_be_accepted(client, mine):
    deck, generation = mine
    _reject(client, generation.id, [1])

    res = _accept(client, generation.id, [1])

    assert res.status_code == 201
    assert res.get_json()["cards"] == []
    assert _statuses(res.get_json()["generation"]) == ["pending", "rejected", "pending"]


def test_an_accepted_card_cannot_be_rejected(client, mine):
    deck, generation = mine
    _accept(client, generation.id, [0])

    res = _reject(client, generation.id, [0])

    assert _statuses(res.get_json()) == ["accepted", "pending", "pending"]
    assert Card.query.filter_by(deck_id=deck.id).count() == 1


# ---- bad indexes --------------------------------------------------------------


@pytest.mark.parametrize(
    "indexes",
    [[], "0", [3], [True], [-1], None, [0.5], ["0"], {"0": 1}],
    ids=["empty", "string", "too-big", "bool", "negative", "null", "float", "string-item", "dict"],
)
def test_bad_indexes_are_422(client, mine, indexes):
    deck, generation = mine
    for res in (_accept(client, generation.id, indexes), _reject(client, generation.id, indexes)):
        assert res.status_code == 422
        error = res.get_json()["error"]
        assert error["field"] == "indexes"
        assert error["message"] == "indexes must be a non-empty list of card positions."
    assert Card.query.count() == 0


def test_missing_indexes_is_422(client, mine):
    deck, generation = mine
    res = client.post(f"/api/generations/{generation.id}/accept", json={})
    assert res.status_code == 422
    assert res.get_json()["error"]["field"] == "indexes"


def test_a_body_that_isnt_json_is_400(client, mine):
    deck, generation = mine
    res = client.post(
        f"/api/generations/{generation.id}/accept", data="not json", content_type="text/plain"
    )
    assert res.status_code == 400


# ---- deleting the deck --------------------------------------------------------------


def test_deleting_the_deck_removes_the_generation_and_its_cards(client, mine, db):
    deck, generation = mine
    _accept(client, generation.id, [0])

    assert client.delete(f"/api/decks/{deck.id}").status_code == 204

    db.session.expire_all()
    assert AiGeneration.query.count() == 0
    assert Card.query.count() == 0
