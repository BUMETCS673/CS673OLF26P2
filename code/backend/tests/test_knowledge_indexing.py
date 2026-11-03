"""Indexing chunks into the real table.

The store and record manager open their own connections, so these writes aren't inside a test's
transaction. Each test clears the tables, and leaves foreign keys empty.
"""

import uuid

import pytest
from langchain_core.documents import Document
from langchain_core.stores import InMemoryByteStore
from sqlalchemy import text

from app.ai.fake import FakeEmbeddings
from app.ai.knowledge import indexing
from app.ai.knowledge.indexing import (
    BATCH_SIZE,
    add_source,
    chunk_id,
    create_record_manager,
    index_chunks,
    with_embedding_cache,
)
from app.ai.knowledge.store import create_store
from app.ai.models import AIRateLimited, AIUnavailable


class CountingEmbeddings(FakeEmbeddings):
    """Keeps every text it embedded, and raises `failures` first."""

    def __init__(self, failures=()):
        self.failures = list(failures)
        self.embedded = []

    def embed_documents(self, texts):
        if self.failures:
            raise self.failures.pop(0)
        self.embedded.extend(texts)
        return super().embed_documents(texts)


def _chunks(count, start=0):
    return [
        Document(
            page_content=f"chunk {index}",
            metadata={"embedding_model": "fake", "chunk_index": index, "page": None},
        )
        for index in range(start, start + count)
    ]


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    async def instantly(_):
        return None

    monkeypatch.setattr(indexing.asyncio, "sleep", instantly)


@pytest.fixture
async def record_manager(engine):
    manager = await create_record_manager(engine)
    yield manager
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM knowledge_chunks"))
        await connection.execute(text("DELETE FROM upsertion_record"))


@pytest.fixture
def store_with(engine):
    async def _store_with(embeddings):
        return await create_store(engine, embeddings)

    return _store_with


async def _saved_count(engine) -> int:
    async with engine.connect() as connection:
        return await connection.scalar(text("SELECT count(*) FROM knowledge_chunks"))


async def test_every_chunk_is_saved(engine, store_with, record_manager):
    store = await store_with(FakeEmbeddings())

    await index_chunks(_chunks(BATCH_SIZE * 2 + 1), store, record_manager)

    assert await _saved_count(engine) == BATCH_SIZE * 2 + 1


async def test_a_retry_only_embeds_what_isnt_saved(engine, store_with, record_manager):
    embeddings = CountingEmbeddings()
    store = await store_with(embeddings)
    await index_chunks(_chunks(3), store, record_manager)
    embeddings.embedded.clear()

    await index_chunks(_chunks(5), store, record_manager)

    assert sorted(embeddings.embedded) == ["chunk 3", "chunk 4"]
    assert await _saved_count(engine) == 5


async def test_progress_is_reported_after_each_batch(store_with, record_manager):
    store = await store_with(FakeEmbeddings())
    seen = []

    async def on_progress(done, total):
        seen.append((done, total))

    await index_chunks(_chunks(BATCH_SIZE + 1), store, record_manager, on_progress)

    assert len(seen) == 2
    assert seen[-1] == (BATCH_SIZE + 1, BATCH_SIZE + 1)


async def test_a_rate_limit_waits_and_tries_again(engine, store_with, record_manager):
    store = await store_with(CountingEmbeddings(failures=[AIRateLimited()]))

    await index_chunks(_chunks(2), store, record_manager)

    assert await _saved_count(engine) == 2


async def test_a_batch_that_keeps_failing_raises_after_the_others_finish(
    engine, store_with, record_manager
):
    class FailsOnOneChunk(CountingEmbeddings):
        """Batches run at once, so a shared failure list would be split between them."""

        def embed_documents(self, texts):
            if "chunk 0" in texts:
                raise AIRateLimited()
            return super().embed_documents(texts)

    store = await store_with(FailsOnOneChunk())

    with pytest.raises(AIRateLimited):
        await index_chunks(_chunks(BATCH_SIZE + 1), store, record_manager)

    assert await _saved_count(engine) > 0


async def test_an_error_that_retrying_wont_fix_raises_at_once(store_with, record_manager):
    embeddings = CountingEmbeddings(failures=[AIUnavailable()])
    store = await store_with(embeddings)

    with pytest.raises(AIUnavailable):
        await index_chunks(_chunks(1), store, record_manager)

    assert embeddings.embedded == []


async def test_identical_text_is_embedded_once_but_saved_for_each_document(
    engine, store_with, record_manager
):
    counting = CountingEmbeddings()
    cached = with_embedding_cache(counting, InMemoryByteStore(), "fake")
    store = await store_with(cached)
    text_ = "The same page."

    for document_marker in (1, 2):
        chunk = Document(
            page_content=text_,
            metadata={"embedding_model": "fake", "chunk_index": document_marker, "page": None},
        )
        await index_chunks([chunk], store, record_manager)

    assert counting.embedded == [text_]
    assert await _saved_count(engine) == 2


def test_the_id_is_a_stable_uuid():
    first = chunk_id(_chunks(1)[0])

    assert uuid.UUID(first)
    assert first == chunk_id(_chunks(1)[0])


def test_the_id_depends_on_content_and_metadata():
    base = _chunks(1)[0]
    other_text = Document(page_content="other", metadata=base.metadata)
    other_page = Document(page_content=base.page_content, metadata={**base.metadata, "page": 2})

    assert len({chunk_id(base), chunk_id(other_text), chunk_id(other_page)}) == 3


def test_source_details_are_added_to_every_chunk():
    chunks = add_source(_chunks(2), embedding_model="model", owner_id=7, document_id=9)

    assert all(chunk.metadata["owner_id"] == 7 for chunk in chunks)
    assert all(chunk.metadata["document_id"] == 9 for chunk in chunks)
    assert all(chunk.metadata["embedding_model"] == "model" for chunk in chunks)
