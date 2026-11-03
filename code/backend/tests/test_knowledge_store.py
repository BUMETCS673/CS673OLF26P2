"""The vector store, against the real table.

The store opens its own connections, so its writes aren't inside a test's transaction. Each test
clears the table instead, and leaves foreign keys empty, since those rows wouldn't be visible.
"""

import pytest
from langchain_core.documents import Document
from sqlalchemy import text

from app.ai.fake import FakeEmbeddings
from app.ai.knowledge.store import create_store


def _chunk(content, chunk_index=0, page=None) -> Document:
    return Document(
        page_content=content,
        metadata={"embedding_model": "fake", "chunk_index": chunk_index, "page": page},
    )


@pytest.fixture
async def store(engine):
    store = await create_store(engine, FakeEmbeddings())
    yield store
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM knowledge_chunks"))


async def test_a_chunk_keeps_its_text_and_metadata(store):
    await store.aadd_documents([_chunk("Cells divide.", chunk_index=3, page=7)])

    [found] = await store.asimilarity_search("Cells divide.", k=1)

    assert found.page_content == "Cells divide."
    assert (found.metadata["chunk_index"], found.metadata["page"]) == (3, 7)


async def test_the_same_text_is_the_closest_match(store):
    await store.aadd_documents([_chunk("Cells divide."), _chunk("Rivers flow.")])

    [found, *_] = await store.asimilarity_search("Rivers flow.", k=1)

    assert found.page_content == "Rivers flow."


async def test_keywords_find_an_exact_term(store):
    await store.aadd_documents([_chunk("Mitochondria make ATP synthase."), _chunk("Rivers flow.")])

    found = await store.asimilarity_search("synthase", k=2, fts_query="synthase")

    assert "Mitochondria make ATP synthase." in [doc.page_content for doc in found]


async def test_a_filter_narrows_the_search(store):
    await store.aadd_documents([_chunk("Cells divide.", chunk_index=1), _chunk("Rivers flow.", 2)])

    found = await store.asimilarity_search("Cells divide.", k=2, filter={"chunk_index": 2})

    assert [doc.page_content for doc in found] == ["Rivers flow."]


async def test_the_full_text_column_is_filled(store, engine):
    await store.aadd_documents([_chunk("Cells divide.")])

    async with engine.connect() as connection:
        filled = await connection.scalar(
            text("SELECT content_tsv IS NOT NULL FROM knowledge_chunks")
        )

    assert filled
