"""Which of the deck's cards a judge compares new cards against."""

from contextlib import asynccontextmanager

import pytest
from langchain_core.stores import InMemoryByteStore

from app.ai.cards import existing
from app.ai.cards.existing import NEAREST_PER_CARD, existing_card_finder
from app.ai.fake import FakeEmbeddings
from app.ai.models import AIUnavailable
from app.ai.schemas import CardDraft
from app.ai.usage import RunUsage
from app.core.settings import EMBEDDING_DIMENSIONS, Settings
from app.repositories.cards import CardRepository


def _vector(x, y):
    return [x, y, *[0.0] * (EMBEDDING_DIMENSIONS - 2)]


@pytest.fixture
def settings(engine):
    return Settings(
        database_url=engine.url.render_as_string(hide_password=False),
        ai_embedder_provider="fake",
    )


@pytest.fixture
def open_cards(session):
    @asynccontextmanager
    async def _open():
        yield CardRepository(session)

    return _open


async def test_likely_repeats_are_each_vectors_nearest_and_the_newest_without_one(
    session, me, make_user, make_deck, make_card
):
    deck, other_deck = await make_deck(me), await make_deck(await make_user("o@example.com"))
    await make_card(deck, front="Near x?", embedding=_vector(1.0, 0.0), embedding_model="m")
    await make_card(deck, front="Near y?", embedding=_vector(0.0, 1.0), embedding_model="m")
    await make_card(deck, front="Far?", embedding=_vector(-1.0, -1.0), embedding_model="m")
    await make_card(deck, front="Older, no vector?")
    await make_card(deck, front="Old model?", embedding=_vector(1.0, 0.0), embedding_model="old")
    await make_card(
        other_deck, front="Other deck?", embedding=_vector(1.0, 0.0), embedding_model="m"
    )

    rows = await CardRepository(session).likely_repeats(
        deck.id, [_vector(1.0, 0.1), _vector(0.1, 1.0), _vector(1.0, 0.0)], "m", 1, 1
    )

    # Near x? is nearest to two vectors and still comes back once.
    assert [row.front for row in rows] == ["Old model?", "Near y?", "Near x?"]


async def test_the_finder_searches_near_each_draft(
    session, me, make_deck, make_card, settings, open_cards
):
    deck = await make_deck(me)
    embedder = FakeEmbeddings()
    for index in range(NEAREST_PER_CARD + 2):
        front = f"Question {index}?"
        vector = embedder.embed_query(f"{front} Answer")
        await make_card(deck, front=front, embedding=vector, embedding_model="fake")
    await make_card(deck, front="Not embedded yet?")

    find = existing_card_finder(deck.id, open_cards, settings, RunUsage())
    found = await find([CardDraft(front="Question 0?", back="Answer")])

    fronts = [card.front for card in found]
    assert len(fronts) == NEAREST_PER_CARD + 1
    assert {"Question 0?", "Not embedded yet?"} <= set(fronts)


async def test_without_embeddings_the_finder_falls_back_to_the_newest(
    session, me, make_deck, make_card, settings, open_cards, monkeypatch
):
    def not_set_up(*_, **__):
        raise AIUnavailable()

    monkeypatch.setattr(existing, "load_embeddings", not_set_up)
    deck = await make_deck(me)
    for index in range(existing.FALLBACK_CARDS + 1):
        await make_card(deck, front=f"Question {index}?")

    find = existing_card_finder(deck.id, open_cards, settings, RunUsage())
    found = await find([CardDraft(front="New?", back="Answer")])

    assert len(found) == existing.FALLBACK_CARDS
    assert found[0].front == f"Question {existing.FALLBACK_CARDS}?"


async def test_the_finder_caches_vectors_for_the_embedding_job(
    me, make_deck, settings, open_cards
):
    deck = await make_deck(me)
    cache = InMemoryByteStore()

    find = existing_card_finder(deck.id, open_cards, settings, RunUsage(), cache=cache)
    await find([CardDraft(front="New?", back="Answer")])

    assert len(list(cache.yield_keys())) == 1
