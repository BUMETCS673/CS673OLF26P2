"""The card routes."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from app.ai.fake import FakeEmbeddings
from app.core.settings import EMBEDDING_DIMENSIONS
from app.models import (
    AiGeneration,
    Card,
    CardReport,
    ChunkReport,
    Job,
    KnowledgeChunk,
    User,
    utcnow,
)
from app.models.job import EMBED_CARDS
from app.repositories.cards import CardRepository
from app.repositories.knowledge import KnowledgeRepository
from app.services import cards as service_module
from app.services.reindex import reindex
from app.services.trust import TRUST_LOSS_REPORTERS


def _error(resp):
    return resp.json()["error"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/decks/1/cards"),
        ("post", "/api/decks/1/cards"),
        ("patch", "/api/cards/1"),
        ("delete", "/api/cards/1"),
    ],
)
async def test_every_route_needs_a_signed_in_user(client, method, path):
    assert (await client.request(method, path)).status_code == 401


async def test_listing_returns_a_decks_cards_in_order(client, me, make_deck, make_card):
    deck = await make_deck(me)
    first = await make_card(deck, front="First?")
    second = await make_card(deck, front="Second?")

    resp = await client.get(f"/api/decks/{deck.id}/cards")

    assert [card["id"] for card in resp.json()] == [first.id, second.id]


async def test_an_empty_deck_has_an_empty_list(client, me, make_deck):
    deck = await make_deck(me)

    assert (await client.get(f"/api/decks/{deck.id}/cards")).json() == []


async def test_creating_a_card_returns_it_in_full(client, me, make_deck):
    deck = await make_deck(me)

    resp = await client.post(
        f"/api/decks/{deck.id}/cards", json={"front": " What divides? ", "back": "Cells"}
    )

    assert resp.status_code == 201
    body = resp.json()
    assert (body["deck_id"], body["front"], body["back"]) == (deck.id, "What divides?", "Cells")
    assert (body["state"], body["due_at"], body["origin"]) == ("new", None, "manual")
    assert "ease_factor" not in body


async def test_origin_cant_be_set_by_the_browser(client, me, make_deck):
    deck = await make_deck(me)

    resp = await client.post(
        f"/api/decks/{deck.id}/cards", json={"front": "Q", "back": "A", "origin": "ai"}
    )

    assert resp.json()["origin"] == "manual"


@pytest.mark.parametrize(
    ("body", "field", "message"),
    [
        ({"back": "A"}, "front", "front is required."),
        ({"front": "  ", "back": "A"}, "front", "front is required."),
        ({"front": "Q"}, "back", "back is required."),
        ({"front": "Q", "back": "x" * 2001}, "back", "back must be at most 2000 characters."),
    ],
)
async def test_a_bad_card_is_422_naming_the_field(client, me, make_deck, body, field, message):
    deck = await make_deck(me)

    resp = await client.post(f"/api/decks/{deck.id}/cards", json=body)

    assert resp.status_code == 422
    assert _error(resp) == {"code": "validation_error", "message": message, "field": field}


@pytest.mark.parametrize("method", ["get", "post"])
async def test_someone_elses_deck_is_404(client, me, make_user, make_deck, method):
    deck = await make_deck(await make_user(email="other@example.com"))
    kwargs = {"json": {"front": "Q", "back": "A"}} if method == "post" else {}

    resp = await client.request(method, f"/api/decks/{deck.id}/cards", **kwargs)

    assert resp.status_code == 404
    assert _error(resp)["message"] == "Deck not found"


async def test_updating_only_changes_what_was_sent(client, me, make_deck, make_card):
    card = await make_card(await make_deck(me), front="Old?", back="Kept")

    resp = await client.patch(f"/api/cards/{card.id}", json={"front": "New?"})

    assert (resp.json()["front"], resp.json()["back"]) == ("New?", "Kept")


async def test_a_blank_field_changes_nothing(client, me, make_deck, make_card):
    deck = await make_deck(me)
    card = await make_card(deck, front="Old?", back="Old")

    resp = await client.patch(f"/api/cards/{card.id}", json={"front": "New?", "back": " "})

    assert resp.status_code == 422
    assert (await client.get(f"/api/decks/{deck.id}/cards")).json()[0]["front"] == "Old?"


@pytest.mark.parametrize("method", ["patch", "delete"])
async def test_someone_elses_card_is_404(client, me, make_user, make_deck, make_card, method):
    deck = await make_deck(await make_user(email="other@example.com"))
    card = await make_card(deck)
    kwargs = {"json": {"front": "Mine now?"}} if method == "patch" else {}

    resp = await client.request(method, f"/api/cards/{card.id}", **kwargs)

    assert resp.status_code == 404
    assert _error(resp)["message"] == "Card not found"


async def test_deleting_a_card_removes_it(client, me, make_deck, make_card):
    deck = await make_deck(me)
    card = await make_card(deck)

    deleted = await client.delete(f"/api/cards/{card.id}")
    again = await client.delete(f"/api/cards/{card.id}")

    assert deleted.status_code == 204
    assert (await client.get(f"/api/decks/{deck.id}/cards")).json() == []
    assert again.status_code == 404


async def test_a_new_card_queues_a_private_embedding(client, session, make_deck, me):
    deck = await make_deck(me)

    response = await client.post(
        f"/api/decks/{deck.id}/cards", json={"front": "Question?", "back": "Answer"}
    )

    job = await session.scalar(select(Job).where(Job.kind == EMBED_CARDS))
    assert job.payload == {"card_ids": [response.json()["id"]], "share": False}


async def test_only_changing_a_cards_text_queues_an_embedding(
    client, session, make_deck, make_card, me
):
    card = await make_card(await make_deck(me), front="Question?", back="Answer")
    count = select(func.count()).select_from(Job).where(Job.kind == EMBED_CARDS)

    await client.patch(f"/api/cards/{card.id}", json={"front": "Question?"})
    assert await session.scalar(count) == 0

    await client.patch(f"/api/cards/{card.id}", json={"front": "New question?"})
    assert await session.scalar(count) == 1


@pytest.fixture
def make_chunk(session):
    async def _make_chunk(**fields) -> KnowledgeChunk:
        chunk = KnowledgeChunk(
            **{
                "langchain_id": uuid.uuid4(),
                "content": "A passage",
                "embedding": [1.0, *[0.0] * (EMBEDDING_DIMENSIONS - 1)],
                "embedding_model": "m",
                "shared": True,
                **fields,
            }
        )
        session.add(chunk)
        await session.commit()
        return chunk

    return _make_chunk


async def _report(client, card):
    return await client.post(f"/api/cards/{card.id}/report")


async def test_reporting_hides_the_cards_copy_and_its_sources(
    client, session, make_deck, make_card, make_chunk, me
):
    deck = await make_deck(me)
    source, unrelated = await make_chunk(), await make_chunk()
    generation = AiGeneration(
        user_id=me.id,
        deck_id=deck.id,
        mode="prompt",
        requested_count=1,
        model="m",
        candidates=[],
        source_chunk_ids=[str(source.langchain_id)],
    )
    session.add(generation)
    await session.commit()
    card = await make_card(deck, generation_id=generation.id)
    copy = await make_chunk(source_card_id=card.id, accepted_by=me.id)

    assert (await _report(client, card)).status_code == 204

    session.expunge_all()
    for chunk in (source, copy):
        refreshed = await session.get(KnowledgeChunk, chunk.langchain_id)
        assert (refreshed.shared, refreshed.hidden) == (False, True)
    other = await session.get(KnowledgeChunk, unrelated.langchain_id)
    assert (other.shared, other.hidden) == (True, False)
    assert (await session.get(Card, card.id)) is not None


async def test_a_second_learners_report_reaches_the_copy_they_confirmed(
    client, session, make_user, make_deck, make_card, make_chunk, me
):
    first = await make_user("first@example.com")
    vector = [1.0, *[0.0] * (EMBEDDING_DIMENSIONS - 1)]
    copy = await make_chunk(accepted_by=first.id, embedding=vector)
    # Same vector but not confirmed, so it stays visible.
    lookalike = await make_chunk(accepted_by=first.id, embedding=vector)
    card = await make_card(
        await make_deck(me),
        embedding=vector,
        embedding_model="m",
        confirmed_chunk_id=copy.langchain_id,
    )

    await _report(client, card)

    session.expunge_all()
    assert (await session.get(KnowledgeChunk, copy.langchain_id)).hidden is True
    assert (await session.get(KnowledgeChunk, lookalike.langchain_id)).hidden is False


async def test_a_hidden_chunk_cant_be_shared_again(session, make_chunk):
    chunk = await make_chunk()
    knowledge = KnowledgeRepository(session)
    await knowledge.hide_chunks([str(chunk.langchain_id)])
    await knowledge.mark_shared([str(chunk.langchain_id)])
    await session.commit()

    session.expunge_all()
    assert (await session.get(KnowledgeChunk, chunk.langchain_id)).shared is False


async def test_someone_elses_card_cant_be_reported(client, make_user, make_deck, make_card, me):
    theirs = await make_deck(await make_user("other@example.com"))
    assert (await _report(client, await make_card(theirs))).status_code == 404


async def test_reporting_a_card_twice_changes_nothing(client, session, make_deck, make_card, me):
    card = await make_card(await make_deck(me))

    assert (await _report(client, card)).status_code == 204
    assert (await _report(client, card)).status_code == 204
    assert await session.scalar(select(func.count()).select_from(CardReport)) == 1


async def test_reports_have_a_daily_limit(client, make_deck, make_card, me, monkeypatch):
    monkeypatch.setattr(service_module, "MAX_REPORTS_PER_DAY", 1)
    deck = await make_deck(me)
    card = await make_card(deck, front="First?")

    assert (await _report(client, card)).status_code == 204
    second = await make_card(deck, front="Second?")
    assert (await _report(client, second)).status_code == 429


@pytest.fixture
def generated_card(session, make_deck, make_card):
    """A card of `user`'s generated from `source`."""

    async def _generated_card(user, source: KnowledgeChunk) -> Card:
        deck = await make_deck(user)
        generation = AiGeneration(
            user_id=user.id,
            deck_id=deck.id,
            mode="prompt",
            requested_count=1,
            model="m",
            candidates=[],
            source_chunk_ids=[str(source.langchain_id)],
        )
        session.add(generation)
        await session.commit()
        return await make_card(deck, generation_id=generation.id)

    return _generated_card


@pytest.fixture
def earlier_reports(session, make_user):
    """Reports from other learners against `target`'s `chunk`."""

    async def _earlier_reports(target, chunk: KnowledgeChunk, count: int, trusted=True) -> None:
        for i in range(count):
            reporter = await make_user(f"reporter{i}@example.com")
            session.add(
                ChunkReport(
                    reporter_id=reporter.id,
                    target_user_id=target.id,
                    chunk_id=chunk.langchain_id,
                    reporter_trusted=trusted,
                )
            )
        await session.commit()

    return _earlier_reports


async def test_a_report_counts_against_the_source_not_the_reporter(
    client, session, make_user, make_chunk, generated_card, me
):
    uploader = await make_user("uploader@example.com")
    source = await make_chunk(owner_id=uploader.id)
    card = await generated_card(me, source)
    await make_chunk(source_card_id=card.id, accepted_by=me.id)

    await _report(client, card)

    reports = [(r.target_user_id, r.chunk_id) for r in await session.scalars(select(ChunkReport))]
    assert reports == [(uploader.id, source.langchain_id)]


@pytest.mark.parametrize("reporter_trusted", [True, False])
async def test_only_a_trusted_last_reporter_takes_the_sources_trust_away(
    client, session, make_user, make_chunk, generated_card, earlier_reports, me, reporter_trusted
):
    uploader = await make_user("uploader@example.com")
    uploader.trusted_at = utcnow() - timedelta(days=1)
    if reporter_trusted:
        me.trusted_at = utcnow() - timedelta(days=1)
    await session.commit()
    source, other = await make_chunk(owner_id=uploader.id), await make_chunk(owner_id=uploader.id)
    await earlier_reports(uploader, source, TRUST_LOSS_REPORTERS - 1)

    await _report(client, await generated_card(me, source))

    session.expunge_all()
    assert (await session.get(KnowledgeChunk, other.langchain_id)).hidden is reporter_trusted
    lost = (await session.get(User, uploader.id)).trust_lost_at is not None
    assert lost is reporter_trusted


async def test_undoing_a_hide_restores_only_what_was_shared(session, make_user, make_chunk):
    user = await make_user("restored@example.com")
    was_shared = await make_chunk(owner_id=user.id)
    was_private = await make_chunk(owner_id=user.id)
    was_private.shared = False
    await session.commit()
    knowledge = KnowledgeRepository(session)

    # Hiding twice mustn't forget the first state.
    await knowledge.hide_user(user.id)
    await knowledge.hide_user(user.id)
    assert await knowledge.unhide_user(user.id) == 2
    await session.commit()

    session.expunge_all()
    restored = await session.get(KnowledgeChunk, was_shared.langchain_id)
    assert (restored.shared, restored.hidden) == (True, False)
    still_private = await session.get(KnowledgeChunk, was_private.langchain_id)
    assert (still_private.shared, still_private.hidden) == (False, False)


async def test_batched_nearest_searches_answer_each_vector_in_order(
    session, make_user, make_chunk
):
    learner = await make_user("learner@example.com")
    first = [1.0, *[0.0] * (EMBEDDING_DIMENSIONS - 1)]
    second = [0.0, 1.0, *[0.0] * (EMBEDDING_DIMENSIONS - 2)]
    between = [1.0, 1.0, *[0.0] * (EMBEDDING_DIMENSIONS - 2)]
    copy = await make_chunk(accepted_by=learner.id, embedding=first)
    await make_chunk(embedding=second)
    knowledge = KnowledgeRepository(session)

    matches = await knowledge.closest_cards([second, first], "m")
    similarities = await knowledge.closest_similarities([between, second], "m")

    assert [match.chunk_id for match in matches] == [str(copy.langchain_id)] * 2
    assert [round(match.similarity, 3) for match in matches] == [0.0, 1.0]
    assert [round(similarity, 3) for similarity in similarities] == [0.707, 1.0]
    assert await knowledge.closest_cards([first], "another model") == [None]
    assert await knowledge.closest_similarities([], "m") == []


async def test_filtered_vector_searches_keep_scanning_the_index(session):
    assert await session.scalar(text("SHOW hnsw.iterative_scan")) == "strict_order"


async def test_has_chunks_only_counts_what_a_search_can_find(session, make_chunk):
    knowledge = KnowledgeRepository(session)
    chunk = await make_chunk()
    assert await knowledge.has_chunks("m") is True

    chunk.shared = False
    await session.commit()
    assert await knowledge.has_chunks("m") is False


async def test_reindex_moves_chunks_and_cards_to_the_new_model(
    session, session_factory, make_chunk, make_deck, make_card, me
):
    chunk = await make_chunk()
    deck = await make_deck(me)
    card = await make_card(deck)

    embedded = await reindex(session_factory, FakeEmbeddings(), "new")

    assert embedded == 2
    session.expunge_all()
    assert (await session.get(KnowledgeChunk, chunk.langchain_id)).embedding_model == "new"
    moved = await session.get(Card, card.id)
    assert moved.embedding_model == "new"
    # Selected on its own, since the column is deferred and async code can't load it lazily.
    assert await session.scalar(select(Card.embedding).where(Card.id == card.id)) is not None
    assert await reindex(session_factory, FakeEmbeddings(), "new") == 0  # nothing left to repeat


async def test_a_document_or_user_can_be_hidden_at_once(session, make_user, make_chunk):
    user = await make_user("gone@example.com")
    uploaded = await make_chunk(owner_id=user.id)
    accepted = await make_chunk(accepted_by=user.id)
    kept = await make_chunk()

    assert await KnowledgeRepository(session).hide_user(user.id) == 2
    await session.commit()

    session.expunge_all()
    assert (await session.get(KnowledgeChunk, uploaded.langchain_id)).hidden is True
    assert (await session.get(KnowledgeChunk, accepted.langchain_id)).hidden is True
    assert (await session.get(KnowledgeChunk, kept.langchain_id)).hidden is False


async def test_similar_cards_come_from_the_same_deck_closest_first(
    session, me, make_user, make_deck, make_card
):
    deck, other_deck = await make_deck(me), await make_deck(await make_user("o@example.com"))

    def vector(x, y):
        return [x, y, *[0.0] * (EMBEDDING_DIMENSIONS - 2)]

    flagged = await make_card(deck, embedding=vector(1.0, 0.0), embedding_model="m")
    await make_card(deck, back="far", embedding=vector(0.0, 1.0), embedding_model="m")
    await make_card(deck, back="close", embedding=vector(1.0, 0.1), embedding_model="m")
    await make_card(deck, back="other model", embedding=vector(1.0, 0.0), embedding_model="x")
    await make_card(other_deck, back="other deck", embedding=vector(1.0, 0.0), embedding_model="m")
    no_vector = await make_card(deck)

    similar = await CardRepository(session).similar_in_deck([flagged.id, no_vector.id], 5)

    assert [row.back for row in similar[flagged.id]] == ["close", "far"]
    assert similar[no_vector.id] == []
