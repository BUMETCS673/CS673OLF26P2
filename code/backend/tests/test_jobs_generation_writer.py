"""How a generation job sets up the card graph for each mode."""

import pytest
from langchain_core.documents import Document
from langchain_core.stores import InMemoryByteStore
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.cards.graph import CardOutcome
from app.ai.cards.prompts import PROMPT_VERSION
from app.ai.judge import PASSED, DocumentEvidence, TopicEvidence
from app.ai.knowledge.indexing import create_record_manager
from app.ai.models import AIRateLimited, AIUnavailable, Role, first_models
from app.ai.schemas import CardDraft
from app.ai.usage import RunUsage
from app.core.errors import InvalidRequest
from app.core.settings import Settings
from app.jobs import generation
from app.jobs.execution import JobContext
from app.jobs.generation import NOT_COVERED, CardRequest, chunks_for, write_cards
from app.jobs.indexing import index_material
from app.models import Document as StoredDocument
from app.models import DocumentFilePart, User

CARD = CardDraft(front="What divides?", back="Cells")
FAKE = Settings(ai_writer_provider="fake", ai_judge_provider="fake")


def _request(mode="prompt", **fields) -> CardRequest:
    values = {
        "mode": mode,
        "count": 3,
        "deck_name": "Biology",
        "deck_description": None,
        "prompt": "The cell cycle" if mode == "prompt" else None,
        "topic": "Mitosis" if mode == "file" else None,
        "document_id": 7 if mode == "file" else None,
        "owner_id": 1,
        "deck_id": 1,
        "existing_fronts": ["What divides?"],
        "models": first_models(FAKE, [Role.WRITER, Role.JUDGE], judged=Role.WRITER),
    }
    return CardRequest(**{**values, **fields})


@pytest.fixture
def settings(engine):
    return Settings(
        database_url=engine.url.render_as_string(hide_password=False),
        ai_writer_provider="fake",
        ai_judge_provider="fake",
        ai_embedder_provider="fake",
    )


class _Retriever:
    def __init__(self, reply):
        self.reply = reply
        self.queries = []

    async def ainvoke(self, query):
        self.queries.append(query)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def graph(monkeypatch):
    """Records the context each run gets, instead of running the graph."""
    contexts = []

    async def run(context):
        contexts.append(context)
        return CardOutcome([CARD], PASSED, 0)

    monkeypatch.setattr(generation, "run_card_graph", run)
    return contexts


@pytest.fixture
def retriever_with(monkeypatch):
    """Replaces the real retriever, and records what it was built with."""
    built = []

    def _retriever_with(reply) -> _Retriever:
        retriever = _Retriever(reply)

        async def build(_engine, _settings, _usage, **fields):
            built.append(fields)
            return retriever

        monkeypatch.setattr(generation, "_build_retriever", build)
        return retriever

    _retriever_with.built = built
    return _retriever_with


@pytest.fixture
def knowledge_base(monkeypatch):
    """Sets whether the knowledge base has anything a search could find."""

    def _knowledge_base(has_chunks) -> None:
        async def answer(*_):
            return has_chunks

        monkeypatch.setattr(generation, "_has_chunks", answer)

    return _knowledge_base


@pytest.mark.parametrize(("count", "chunks"), [(1, 6), (3, 6), (5, 10), (10, 20), (25, 20)])
def test_more_cards_get_more_chunks_within_limits(count, chunks):
    assert chunks_for(count) == chunks


async def test_file_mode_finds_the_material_itself(engine, settings, graph, retriever_with):
    found = [Document(page_content="Mitosis has phases."), Document(page_content="More.")]
    retriever = retriever_with(found)

    result = await write_cards(_request("file"), RunUsage(), engine, settings)

    assert retriever.queries == ["Mitosis"]
    assert retriever_with.built == [{"document_id": 7, "k": 6, "cache": None}]
    context = graph[0]
    assert context.retriever is None  # the model gets no tool in this mode
    assert "Mitosis has phases.\n\nMore." in context.body
    assert "<focus>\nMitosis\n</focus>" in context.body
    assert context.evidence == DocumentEvidence("Mitosis", "Mitosis has phases.\n\nMore.")
    assert (result.drafts, result.verification) == ([CARD], PASSED)
    assert result.prompt_version == PROMPT_VERSION


async def test_a_file_that_doesnt_cover_the_topic_fails_without_a_model_call(
    engine, settings, graph, retriever_with
):
    retriever_with([])

    with pytest.raises(InvalidRequest) as refused:
        await write_cards(_request("file"), RunUsage(), engine, settings)

    assert refused.value.message == NOT_COVERED
    assert graph == []


async def test_a_rate_limited_file_search_is_left_for_the_job_to_retry(
    engine, settings, graph, retriever_with
):
    retriever_with(AIRateLimited())

    with pytest.raises(AIRateLimited):
        await write_cards(_request("file"), RunUsage(), engine, settings)


async def test_prompt_mode_offers_the_writer_a_search(
    engine, settings, graph, retriever_with, knowledge_base
):
    retriever = retriever_with([])
    knowledge_base(True)

    await write_cards(_request(), RunUsage(), engine, settings)

    assert retriever_with.built == [{"document_id": None, "k": 6, "viewer_id": 1, "cache": None}]
    context = graph[0]
    assert context.retriever is retriever
    assert retriever.queries == []  # the model decides whether to search
    assert context.evidence == TopicEvidence("The cell cycle")
    assert "The cell cycle" in context.body


async def test_an_empty_knowledge_base_offers_no_search(
    engine, settings, graph, retriever_with, knowledge_base
):
    retriever_with([])
    knowledge_base(False)

    await write_cards(_request(), RunUsage(), engine, settings)

    assert graph[0].retriever is None


async def test_prompt_mode_works_without_embeddings_set_up(
    engine, settings, graph, knowledge_base, monkeypatch
):
    knowledge_base(True)

    async def not_set_up(*_, **__):
        raise AIUnavailable()

    monkeypatch.setattr(generation, "_build_retriever", not_set_up)

    await write_cards(_request(), RunUsage(), engine, settings)

    assert graph[0].retriever is None


async def test_the_deck_reaches_the_graph(engine, settings, graph, knowledge_base):
    knowledge_base(False)

    await write_cards(_request(deck_name="Biology 101"), RunUsage(), engine, settings)

    context = graph[0]
    assert "Biology 101" in context.body
    assert context.count == 3
    assert context.existing_fronts == ["What divides?"]


# --- through the real store ---------------------------------------------------------------


@pytest.fixture
async def indexed(engine, settings):
    """A saved file, indexed by the real job with fake models. Real commits for the store."""
    await create_record_manager(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = User(email="writer@example.com", password_hash="not-a-real-hash")
        session.add(user)
        await session.flush()
        document = StoredDocument(
            user_id=user.id,
            filename="n",
            content_hash="h",
            mime_type="text/plain",
            size_bytes=13,
        )
        session.add(document)
        await session.flush()
        session.add(DocumentFilePart(document_id=document.id, number=0, data=b"Cells divide."))
        await session.commit()

    async def report(_):
        pass

    context = JobContext(1, user.id, {"document_id": document.id}, factory, report)
    await index_material(context, engine, settings, InMemoryByteStore())
    yield document.id
    async with engine.begin() as connection:
        await connection.execute(delete(User).where(User.id == user.id))
        await connection.execute(text("DELETE FROM upsertion_record"))


async def test_file_mode_runs_end_to_end_with_fake_models(engine, settings, indexed):
    # Fake embeddings match only identical text, so the topic is the chunk's exact text.
    request = _request("file", topic="Cells divide.", document_id=indexed, existing_fronts=[])

    result = await write_cards(request, RunUsage(), engine, settings)

    assert len(result.drafts) == 3
    assert result.verification == PASSED


async def test_prompt_mode_runs_end_to_end_with_fake_models(engine, settings, indexed):
    result = await write_cards(_request(existing_fronts=[]), RunUsage(), engine, settings)

    assert len(result.drafts) == 3
