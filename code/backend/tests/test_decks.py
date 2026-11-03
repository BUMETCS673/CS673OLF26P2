"""The deck routes."""

from datetime import timedelta

import pytest
from sqlalchemy import event

from app.models import Card, utcnow
from app.scheduler import NEW_CARDS_PER_SESSION, REVIEWS_PER_SESSION

ZERO = {"learning": 0, "review": 0, "new": 0}


def _error(resp):
    return resp.json()["error"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/decks"),
        ("post", "/api/decks"),
        ("get", "/api/decks/1"),
        ("patch", "/api/decks/1"),
        ("delete", "/api/decks/1"),
    ],
)
async def test_every_route_needs_a_signed_in_user(client, method, path):
    assert (await client.request(method, path)).status_code == 401


async def test_a_list_has_only_my_decks_in_order(client, me, make_user, make_deck):
    first = await make_deck(me, name="First")
    second = await make_deck(me, name="Second")
    await make_deck(await make_user(email="other@example.com"))

    resp = await client.get("/api/decks")

    assert [deck["id"] for deck in resp.json()] == [first.id, second.id]


async def test_creating_a_deck_returns_it_in_full(client, me):
    resp = await client.post("/api/decks", json={"name": "  Biology ", "description": " Cells "})

    assert resp.status_code == 201
    body = resp.json()
    assert (body["name"], body["description"]) == ("Biology", " Cells ")
    assert body["card_count"] == 0
    assert body["due_counts"] == ZERO
    assert body["created_at"].endswith("Z")


@pytest.mark.parametrize(
    ("body", "field", "message"),
    [
        ({}, "name", "name is required."),
        ({"name": "  "}, "name", "name is required."),
        ({"name": 7}, "name", "name is required."),
        ({"name": "x" * 121}, "name", "name must be at most 120 characters."),
        ({"name": "A", "description": 7}, "description", "description must be text."),
        (
            {"name": "A", "description": "x" * 1001},
            "description",
            "description must be at most 1000 characters.",
        ),
    ],
)
async def test_a_bad_deck_is_422_naming_the_field(client, me, body, field, message):
    resp = await client.post("/api/decks", json=body)

    assert resp.status_code == 422
    assert _error(resp) == {"code": "validation_error", "message": message, "field": field}


async def test_a_body_that_isnt_an_object_is_400(client, me):
    resp = await client.post("/api/decks", json=[1, 2])

    assert resp.status_code == 400


async def test_getting_a_deck_counts_its_cards(client, me, make_deck, make_card):
    deck = await make_deck(me)
    await make_card(deck)
    await make_card(deck)

    resp = await client.get(f"/api/decks/{deck.id}")

    assert resp.json()["card_count"] == 2


async def test_a_missing_deck_is_404(client, me):
    resp = await client.get("/api/decks/999")

    assert resp.status_code == 404
    assert _error(resp)["message"] == "Deck not found"


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
async def test_someone_elses_deck_is_404_not_403(client, me, make_user, make_deck, method):
    deck = await make_deck(await make_user(email="other@example.com"))
    kwargs = {"json": {"name": "Mine now"}} if method == "patch" else {}

    resp = await client.request(method, f"/api/decks/{deck.id}", **kwargs)

    assert resp.status_code == 404


async def test_updating_only_changes_what_was_sent(client, me, make_deck):
    deck = await make_deck(me, name="Old", description="Kept")

    resp = await client.patch(f"/api/decks/{deck.id}", json={"name": "New"})

    assert (resp.json()["name"], resp.json()["description"]) == ("New", "Kept")


async def test_a_description_can_be_cleared_with_null(client, me, make_deck):
    deck = await make_deck(me, description="Old")

    resp = await client.patch(f"/api/decks/{deck.id}", json={"description": None})

    assert resp.json()["description"] is None


@pytest.mark.parametrize("name", ["  ", None])
async def test_a_blank_name_changes_nothing(client, me, make_deck, name):
    deck = await make_deck(me, name="Old")

    resp = await client.patch(f"/api/decks/{deck.id}", json={"name": name})

    assert resp.status_code == 422
    assert (await client.get(f"/api/decks/{deck.id}")).json()["name"] == "Old"


async def test_deleting_a_deck_deletes_its_cards(client, session, me, make_deck, make_card):
    deck = await make_deck(me)
    card = await make_card(deck)

    assert (await client.delete(f"/api/decks/{deck.id}")).status_code == 204

    assert (await client.get(f"/api/decks/{deck.id}")).status_code == 404
    session.expunge_all()
    assert await session.get(Card, card.id) is None


# --- due counts --------------------------------------------------------------------------


async def test_one_card_in_each_state_counts_relearning_as_learning(
    client, me, make_deck, make_card
):
    deck = await make_deck(me)
    due = utcnow() - timedelta(minutes=1)
    await make_card(deck)
    await make_card(deck, state="learning", due_at=due)
    await make_card(deck, state="review", due_at=due)
    await make_card(deck, state="relearning", due_at=due)

    resp = await client.get(f"/api/decks/{deck.id}")

    assert resp.json()["due_counts"] == {"learning": 2, "review": 1, "new": 1}


async def test_cards_not_due_yet_arent_counted(client, me, make_deck, make_card):
    deck = await make_deck(me)
    await make_card(deck, state="review", due_at=utcnow() + timedelta(days=1))
    await make_card(deck, state="learning", due_at=utcnow() + timedelta(minutes=30))

    assert (await client.get(f"/api/decks/{deck.id}")).json()["due_counts"] == ZERO


async def test_a_learning_card_due_soon_is_counted(client, me, make_deck, make_card):
    deck = await make_deck(me)
    await make_card(deck, state="learning", due_at=utcnow() + timedelta(minutes=15))

    resp = await client.get(f"/api/decks/{deck.id}")

    assert resp.json()["due_counts"]["learning"] == 1


async def test_new_and_review_stop_at_the_session_limits(client, session, me, make_deck):
    deck = await make_deck(me)
    due = utcnow() - timedelta(minutes=1)
    session.add_all(
        Card(deck_id=deck.id, front="Q", back="A") for _ in range(NEW_CARDS_PER_SESSION + 1)
    )
    session.add_all(
        Card(deck_id=deck.id, front="Q", back="A", state="review", due_at=due)
        for _ in range(REVIEWS_PER_SESSION + 1)
    )
    await session.commit()

    counts = (await client.get(f"/api/decks/{deck.id}")).json()["due_counts"]

    assert (counts["new"], counts["review"]) == (NEW_CARDS_PER_SESSION, REVIEWS_PER_SESSION)


async def test_listing_five_decks_takes_as_many_queries_as_one(
    client, engine, me, make_deck, make_card
):
    async def queries_to_list() -> int:
        count = 0

        def on_query(*_):
            nonlocal count
            count += 1

        event.listen(engine.sync_engine, "before_cursor_execute", on_query)
        await client.get("/api/decks")
        event.remove(engine.sync_engine, "before_cursor_execute", on_query)
        return count

    await make_card(await make_deck(me))
    one = await queries_to_list()
    for _ in range(4):
        await make_card(await make_deck(me))

    assert await queries_to_list() == one
