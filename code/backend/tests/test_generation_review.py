"""Accepting and rejecting suggested cards, and suggesting what to learn next."""

import pytest
from sqlalchemy import func, select

from app.ai.models import AIRateLimited, AIUnavailable
from app.core.settings import get_settings
from app.models import AiGeneration, AiUsage, Card, Job
from app.models.job import EMBED_CARDS
from app.services import generations as generations_service
from app.services.budget import SUGGESTIONS, BudgetService


@pytest.fixture
async def deck(make_deck, me):
    return await make_deck(me)


@pytest.fixture
async def generation(session, me, deck) -> AiGeneration:
    generation = AiGeneration(
        user_id=me.id,
        deck_id=deck.id,
        mode="prompt",
        requested_count=3,
        model="m",
        candidates=[
            {"front": f"Q{index}", "back": f"A{index}", "status": "pending"} for index in range(3)
        ],
    )
    session.add(generation)
    await session.commit()
    return generation


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def _accept(client, generation, indexes):
    return await client.post(f"/api/generations/{generation.id}/accept", json={"indexes": indexes})


async def _reject(client, generation, indexes):
    return await client.post(f"/api/generations/{generation.id}/reject", json={"indexes": indexes})


def _statuses(body) -> list[str]:
    return [candidate["status"] for candidate in body["candidates"]]


# --- accepting and rejecting --------------------------------------------------------------


async def test_accepting_creates_cards_and_queues_their_embedding(client, session, me, generation):
    response = await _accept(client, generation, [0, 2])

    assert response.status_code == 201
    body = response.json()
    assert [card["front"] for card in body["cards"]] == ["Q0", "Q2"]
    assert all(card["origin"] == "ai" for card in body["cards"])
    assert _statuses(body["generation"]) == ["accepted", "pending", "accepted"]
    saved = await session.scalar(select(Card).where(Card.front == "Q0"))
    assert saved.generation_id == generation.id
    job = await session.scalar(select(Job))
    assert (job.user_id, job.kind) == (me.id, EMBED_CARDS)
    assert job.payload == {"card_ids": [card["id"] for card in body["cards"]]}


async def test_rejecting_marks_cards_and_creates_nothing(client, session, generation):
    response = await _reject(client, generation, [1])

    assert response.status_code == 200
    assert _statuses(response.json()) == ["pending", "rejected", "pending"]
    assert await _count(session, Card) == 0
    assert await _count(session, Job) == 0


async def test_a_decision_is_final(client, session, generation):
    await _reject(client, generation, [0])
    await _accept(client, generation, [1])

    response = await _accept(client, generation, [0, 1])

    assert response.status_code == 201
    assert response.json()["cards"] == []
    assert _statuses(response.json()["generation"]) == ["rejected", "accepted", "pending"]
    assert await _count(session, Card) == 1
    assert await _count(session, Job) == 1  # none for an accept that added no cards


async def test_repeated_indexes_count_once(client, session, generation):
    await _accept(client, generation, [1, 1, 1])

    assert await _count(session, Card) == 1


@pytest.mark.parametrize("indexes", [[], "0", [3], [-1], [True], ["0"], [1.5]])
async def test_bad_indexes_are_refused(client, session, generation, indexes):
    for decide in (_accept, _reject):
        response = await decide(client, generation, indexes)

        assert response.status_code == 422
        assert response.json()["error"]["field"] == "indexes"
    assert await _count(session, Card) == 0


async def test_someone_elses_batch_doesnt_exist(client, generation, make_user, login_as):
    await login_as(await make_user(email="other@example.com"))

    assert (await _accept(client, generation, [0])).status_code == 404
    assert (await _reject(client, generation, [0])).status_code == 404


async def test_deciding_needs_a_signed_in_user(client):
    response = await client.post("/api/generations/1/accept", json={"indexes": [0]})

    assert response.status_code == 401


# --- suggestions --------------------------------------------------------------------------


def _url(deck) -> str:
    return f"/api/decks/{deck.id}/suggestions"


@pytest.fixture
def fake_writer(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_writer_provider", "fake")


async def test_suggestions_return_three_topics_and_record_usage(client, session, deck, fake_writer):
    response = await client.post(_url(deck))

    assert response.status_code == 200
    assert len(response.json()["topics"]) == 3
    assert await session.scalar(select(AiUsage.feature)) == SUGGESTIONS


async def test_suggestions_see_the_decks_cards(client, deck, make_card, monkeypatch, fake_writer):
    await make_card(deck, front="What divides?", back="Cells")
    seen = []

    async def suggest(_model, name, _description, existing):
        seen.append((name, [card.front for card in existing]))
        return ["Topic"]

    monkeypatch.setattr(generations_service, "suggest_deck_topics", suggest)

    response = await client.post(_url(deck))

    assert response.json() == {"topics": ["Topic"]}
    assert seen == [(deck.name, ["What divides?"])]


async def test_someone_elses_deck_has_no_suggestions(client, me, make_deck, make_user):
    other = await make_user(email="other@example.com")

    assert (await client.post(_url(await make_deck(other)))).status_code == 404


async def test_suggestions_have_a_daily_limit(client, deck, fake_writer, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_suggestions_user_daily_limit", 1)

    assert (await client.post(_url(deck))).status_code == 200
    assert (await client.post(_url(deck))).status_code == 429


async def test_a_full_model_limit_refuses_suggestions(client, deck, fake_writer, monkeypatch):
    async def full(*_, **__):
        return False

    monkeypatch.setattr(BudgetService, "within_model_limits", full)

    assert (await client.post(_url(deck))).status_code == 429


@pytest.mark.parametrize(("error", "status"), [(AIRateLimited(), 429), (AIUnavailable(), 503)])
async def test_a_failed_model_call_is_reported(
    client, deck, fake_writer, monkeypatch, error, status
):
    async def fail(*_):
        raise error

    monkeypatch.setattr(generations_service, "suggest_deck_topics", fail)

    assert (await client.post(_url(deck))).status_code == status
