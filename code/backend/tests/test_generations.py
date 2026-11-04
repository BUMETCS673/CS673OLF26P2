"""Starting card generation, and the job that saves its batch."""

import pytest
from sqlalchemy import func, select

from app.ai.models import AIRateLimited
from app.ai.schemas import CardDraft
from app.ai.usage import RunUsage
from app.core.errors import NotFound
from app.core.settings import Settings, get_settings
from app.jobs.execution import JobContext
from app.jobs.generation import DECK_GONE, CardResult, generate_cards
from app.jobs.tasks import HANDLERS
from app.models import AiGeneration, AiUsage, Card, Deck, Document, Job
from app.models.document import READY
from app.models.job import GENERATE_CARDS, QUEUED
from app.repositories.generations import GenerationRepository
from app.schemas.generations import MAX_CARDS
from app.services.budget import GENERATE, BudgetService

PROMPT_BODY = {"mode": "prompt", "count": 3, "prompt": "The cell cycle"}


@pytest.fixture
async def deck(make_deck, me) -> Deck:
    return await make_deck(me)


@pytest.fixture
def make_document(session, me):
    async def _make_document(status=READY) -> Document:
        document = Document(
            user_id=me.id,
            filename="cells.pdf",
            content_hash="h",
            mime_type="application/pdf",
            size_bytes=1,
            status=status,
        )
        session.add(document)
        await session.commit()
        return document

    return _make_document


def _url(deck) -> str:
    return f"/api/decks/{deck.id}/generate"


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


# --- starting -----------------------------------------------------------------------------


async def test_signing_in_is_required(client):
    assert (await client.post("/api/decks/1/generate", json=PROMPT_BODY)).status_code == 401
    assert (await client.get("/api/generations/1")).status_code == 401


async def test_generating_from_a_prompt_queues_a_job(client, session, me, deck):
    response = await client.post(_url(deck), json=PROMPT_BODY)

    assert response.status_code == 202
    job = await session.get(Job, response.json()["job_id"])
    assert (job.user_id, job.kind, job.status) == (me.id, GENERATE_CARDS, QUEUED)
    assert job.payload == {
        **PROMPT_BODY,
        "document_id": None,
        "topic": None,
        "deck_id": deck.id,
        "file_name": None,
    }


async def test_generating_from_a_file_queues_a_job(client, session, deck, make_document):
    document = await make_document()
    body = {"mode": "file", "count": 2, "document_id": document.id, "topic": "Mitosis"}

    response = await client.post(_url(deck), json=body)

    assert response.status_code == 202
    job = await session.get(Job, response.json()["job_id"])
    assert job.payload["file_name"] == "cells.pdf"
    assert job.payload["prompt"] is None


async def test_a_file_must_be_ready(client, deck, make_document):
    document = await make_document(status="processing")
    body = {"mode": "file", "count": 2, "document_id": document.id, "topic": "Mitosis"}

    response = await client.post(_url(deck), json=body)

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "document_id"


async def test_someone_elses_deck_doesnt_exist(client, me, make_deck, make_user):
    other = await make_user(email="other@example.com")
    deck = await make_deck(other)

    assert (await client.post(_url(deck), json=PROMPT_BODY)).status_code == 404


async def test_someone_elses_file_doesnt_exist(client, session, deck, make_user):
    other = await make_user(email="other@example.com")
    document = Document(
        user_id=other.id, filename="n", content_hash="h", mime_type="text/plain", size_bytes=1
    )
    session.add(document)
    await session.commit()
    body = {"mode": "file", "count": 2, "document_id": document.id, "topic": "Mitosis"}

    assert (await client.post(_url(deck), json=body)).status_code == 404


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"mode": "guess"}, "mode"),
        ({"count": 0}, "count"),
        ({"count": MAX_CARDS + 1}, "count"),
        ({"count": True}, "count"),
        ({"count": "3"}, "count"),
        ({"prompt": "   "}, "prompt"),
        ({"prompt": "x" * 2001}, "prompt"),
    ],
)
async def test_a_bad_prompt_request_is_refused(client, session, deck, change, field):
    response = await client.post(_url(deck), json={**PROMPT_BODY, **change})

    assert response.status_code == 422
    assert response.json()["error"]["field"] == field
    assert await _count(session, Job) == 0


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"mode": "file", "count": 2, "topic": "Mitosis"}, "document_id"),
        ({"mode": "file", "count": 2, "document_id": True, "topic": "Mitosis"}, "document_id"),
        ({"mode": "file", "count": 2, "document_id": 1}, "topic"),
    ],
)
async def test_a_bad_file_request_is_refused(client, deck, body, field):
    response = await client.post(_url(deck), json=body)

    assert response.status_code == 422
    assert response.json()["error"]["field"] == field


async def test_jobs_still_waiting_count_toward_the_daily_limit(client, deck, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_daily_limit", 2)

    assert (await client.post(_url(deck), json=PROMPT_BODY)).status_code == 202
    assert (await client.post(_url(deck), json=PROMPT_BODY)).status_code == 202
    assert (await client.post(_url(deck), json=PROMPT_BODY)).status_code == 429


async def test_a_batch_with_no_cards_doesnt_use_the_allowance(
    client, session, me, deck, monkeypatch
):
    monkeypatch.setattr(get_settings(), "ai_daily_limit", 1)
    session.add(_generation(me, deck, empty=True))
    await session.commit()

    assert (await client.post(_url(deck), json=PROMPT_BODY)).status_code == 202


async def test_a_full_model_limit_refuses_a_run(client, deck, monkeypatch):
    async def full(*_, **__):
        return False

    monkeypatch.setattr(BudgetService, "within_model_limits", full)

    assert (await client.post(_url(deck), json=PROMPT_BODY)).status_code == 429


# --- reading ------------------------------------------------------------------------------


def _generation(user, deck, empty=False, job_id=None) -> AiGeneration:
    return AiGeneration(
        job_id=job_id,
        user_id=user.id,
        deck_id=deck.id,
        mode="prompt",
        requested_count=1,
        model="m",
        empty=empty,
        candidates=[] if empty else [{"front": "Q", "back": "A", "status": "pending"}],
    )


async def test_a_batch_can_be_read(client, session, me, deck):
    generation = _generation(me, deck)
    session.add(generation)
    await session.commit()

    response = await client.get(f"/api/generations/{generation.id}")

    assert response.status_code == 200
    assert response.json()["candidates"] == [{"front": "Q", "back": "A", "status": "pending"}]


async def test_someone_elses_batch_doesnt_exist(client, session, deck, me, make_user, login_as):
    generation = _generation(me, deck)
    session.add(generation)
    await session.commit()
    await login_as(await make_user(email="other@example.com"))

    assert (await client.get(f"/api/generations/{generation.id}")).status_code == 404


# --- the job ------------------------------------------------------------------------------


@pytest.fixture
def settings(engine):
    return Settings(
        database_url=engine.url.render_as_string(hide_password=False),
        ai_writer_provider="fake",
    )


@pytest.fixture
def make_context(session, session_factory, me, deck):
    async def _make_context(**payload) -> JobContext:
        full = {
            **PROMPT_BODY,
            "document_id": None,
            "topic": None,
            "deck_id": deck.id,
            "file_name": None,
            **payload,
        }
        job = Job(user_id=me.id, kind=GENERATE_CARDS, payload=full)
        session.add(job)
        await session.commit()

        async def report(_):
            pass

        return JobContext(job.id, me.id, full, session_factory, report)

    return _make_context


def _writes(*drafts, seen=None):
    async def write(request, usage):
        if seen is not None:
            seen.append(request)
        usage.for_role("writer", "m").count_call()
        return CardResult(list(drafts), "passed", "v1")

    return write


async def test_the_job_saves_a_batch_waiting_for_review(session, make_context, settings):
    context = await make_context()

    result = await generate_cards(context, settings, _writes(CardDraft(front="Q", back="A")))

    generation = await session.get(AiGeneration, result["generation_id"])
    assert generation.job_id == context.job_id
    assert generation.prompt == "The cell cycle"
    assert (generation.verification, generation.empty) == ("passed", False)
    assert generation.candidates == [{"front": "Q", "back": "A", "status": "pending"}]


async def test_a_run_gets_the_deck_and_its_cards(session, me, deck, make_context, settings):
    session.add(Card(deck_id=deck.id, front="Old Q", back="Old A"))
    await session.commit()
    seen = []

    await generate_cards(await make_context(), settings, _writes(seen=seen))

    assert seen[0].deck_name == deck.name
    assert seen[0].owner_id == me.id
    assert seen[0].deck_id == deck.id
    assert seen[0].existing_fronts == ["Old Q"]


async def test_a_run_with_no_cards_is_saved_as_empty(session, make_context, settings):
    result = await generate_cards(await make_context(), settings, _writes())

    assert (await session.get(AiGeneration, result["generation_id"])).empty is True


async def test_a_retry_reuses_the_batch_already_saved(session, make_context, settings):
    context = await make_context()
    first = await generate_cards(context, settings, _writes(CardDraft(front="Q", back="A")))

    async def must_not_run(*_):
        pytest.fail("the batch is already saved")

    assert await generate_cards(context, settings, must_not_run) == first
    assert await _count(session, AiGeneration) == 1


async def test_two_workers_saving_at_once_keep_one_batch(
    session, make_context, settings, monkeypatch
):
    context = await make_context()
    await generate_cards(context, settings, _writes(CardDraft(front="Q", back="A")))
    real = GenerationRepository.get_for_job
    misses = iter([None])

    async def miss_once(self, job_id):
        try:
            return next(misses)
        except StopIteration:
            return await real(self, job_id)

    monkeypatch.setattr(GenerationRepository, "get_for_job", miss_once)

    await generate_cards(context, settings, _writes(CardDraft(front="Q2", back="A2")))

    assert await _count(session, AiGeneration) == 1


async def test_a_deleted_deck_fails_the_job(me, make_context, settings):
    context = await make_context(deck_id=0)

    with pytest.raises(NotFound) as gone:
        await generate_cards(context, settings, _writes())

    assert gone.value.message == DECK_GONE


async def test_a_failed_run_saves_no_batch_but_counts_its_spending(
    session, make_context, settings
):
    async def fail(_, usage: RunUsage):
        usage.for_role("writer", "m").count_call()
        raise AIRateLimited()

    with pytest.raises(AIRateLimited):
        await generate_cards(await make_context(), settings, fail)

    assert await _count(session, AiGeneration) == 0
    assert (await session.scalar(select(AiUsage.feature))) == GENERATE


def test_the_job_is_registered():
    assert GENERATE_CARDS in HANDLERS
