"""Searching the knowledge base, against the real table.

The store opens its own connections, so rows it needs to see, like a document, are committed here,
and each test clears what it wrote.
"""

from types import SimpleNamespace

import pytest
from langchain_core.documents import Document
from sqlalchemy import text

from app.ai.fake import FakeEmbeddings
from app.ai.knowledge import tools
from app.ai.knowledge.retrieval import MAX_PER_OTHER_USER, KnowledgeRetriever, labelled_text
from app.ai.knowledge.store import create_store
from app.ai.knowledge.tools import NOTHING_FOUND, KnowledgeContext, search_materials
from app.ai.models import AIRateLimited
from app.core.settings import EMBEDDING_DIMENSIONS


def _towards(first, second=0.0):
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[0], vector[1] = first, second
    return vector


class PointedEmbeddings(FakeEmbeddings):
    """Chosen vectors per text, so tests control what's close. Queries use the first axis."""

    def __init__(self, vectors=None):
        self.vectors = vectors or {}

    def embed_documents(self, texts):
        return [self.vectors.get(text, _towards(1.0)) for text in texts]

    def embed_query(self, text):
        return _towards(1.0)


def _chunk(content, model="fake", **metadata) -> Document:
    fields = {"embedding_model": model, "shared": True, **metadata}
    return Document(page_content=content, metadata=fields)


@pytest.fixture
async def clean(engine):
    yield
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM knowledge_chunks"))
        await connection.execute(text("DELETE FROM users WHERE email LIKE '%@retrieval.test'"))


@pytest.fixture
def retriever_with(engine, clean):
    async def _retriever_with(chunks, vectors=None, **options):
        embeddings = PointedEmbeddings(vectors)
        store = await create_store(engine, embeddings)
        await store.aadd_documents(chunks)
        return KnowledgeRetriever(
            store=store, engine=engine, embeddings=embeddings, embedding_model="fake", **options
        )

    return _retriever_with


async def _committed_document(engine, email) -> tuple[int, int]:
    async with engine.begin() as connection:
        user_id = await connection.scalar(
            text("""
                INSERT INTO users (email, password_hash, created_at)
                VALUES (:email, 'x', now()) RETURNING id
            """),
            {"email": email},
        )
        document_id = await connection.scalar(
            text("""
                INSERT INTO documents (
                    user_id, filename, content_hash, mime_type, size_bytes, status, stage,
                    chunks_total, chunks_done, created_at, updated_at
                )
                VALUES (
                    :user_id, 'n.pdf', 'h', 'application/pdf', 1, 'ready', 'queued', 0, 0,
                    now(), now()
                )
                RETURNING id
            """),
            {"user_id": user_id},
        )
    return user_id, document_id


def _contents(documents):
    return [document.page_content for document in documents]


async def test_the_closest_chunk_comes_first(retriever_with):
    retriever = await retriever_with(
        [_chunk("further"), _chunk("closest")],
        {"further": _towards(1.0, 0.5), "closest": _towards(1.0)},
    )

    assert _contents(await retriever.ainvoke("cells"))[0] == "closest"


async def test_a_topic_the_material_doesnt_cover_finds_nothing(retriever_with):
    retriever = await retriever_with([_chunk("unrelated")], {"unrelated": _towards(0.0, 1.0)})

    assert await retriever.ainvoke("cells") == []


async def test_an_empty_knowledge_base_finds_nothing(retriever_with):
    retriever = await retriever_with([])

    assert await retriever.ainvoke("cells") == []


async def test_keywords_find_an_exact_term_vectors_miss(retriever_with):
    retriever = await retriever_with(
        [_chunk("close by meaning"), _chunk("mentions synthase")],
        {"close by meaning": _towards(1.0), "mentions synthase": _towards(0.0, 1.0)},
    )

    assert "mentions synthase" in _contents(await retriever.ainvoke("synthase"))


async def test_every_word_in_one_chunk_passes_when_the_vectors_are_too_far(retriever_with):
    retriever = await retriever_with(
        [_chunk("mentions synthase")], {"mentions synthase": _towards(0.0, 1.0)}
    )

    assert _contents(await retriever.ainvoke("synthase")) == ["mentions synthase"]
    assert await retriever.ainvoke("synthase inhibitors") == []


async def test_a_chunk_that_isnt_shared_stays_out_of_shared_search(engine, retriever_with):
    _, document_id = await _committed_document(engine, "private@retrieval.test")
    private = _chunk("private passage", shared=None, document_id=document_id)
    vectors = {"private passage": _towards(1.0)}

    shared_search = await retriever_with([private], vectors)
    assert await shared_search.ainvoke("private passage") == []

    own_file = shared_search.model_copy(update={"document_id": document_id})
    assert _contents(await own_file.ainvoke("private passage")) == ["private passage"]


def _from(owner, *texts):
    return [_chunk(text, owner_id=owner) for text in texts]


async def test_one_other_learner_cant_fill_a_search(engine, retriever_with):
    other, _ = await _committed_document(engine, "other@retrieval.test")
    me, _ = await _committed_document(engine, "me@retrieval.test")
    theirs = [f"theirs {number}" for number in range(MAX_PER_OTHER_USER + 2)]
    mine = [f"mine {number}" for number in range(MAX_PER_OTHER_USER + 2)]
    texts = [*theirs, *mine]

    retriever = await retriever_with(
        [*_from(other, *theirs), *_from(me, *mine)],
        {text: _towards(1.0) for text in texts},
        viewer_id=me,
    )

    found = _contents(await retriever.ainvoke("cells"))
    assert sum(text.startswith("theirs") for text in found) == MAX_PER_OTHER_USER
    assert sum(text.startswith("mine") for text in found) == len(mine)


async def test_a_passage_two_learners_uploaded_ranks_first(engine, retriever_with):
    first, _ = await _committed_document(engine, "first@retrieval.test")
    second, _ = await _committed_document(engine, "second@retrieval.test")
    retriever = await retriever_with(
        [*_from(first, "closest", "agreed"), *_from(second, "agreed")],
        {"closest": _towards(1.0), "agreed": _towards(1.0, 0.5)},
    )

    assert _contents(await retriever.ainvoke("cells")) == ["agreed", "closest"]


async def test_results_say_where_they_came_from(engine, retriever_with):
    other, _ = await _committed_document(engine, "other@retrieval.test")
    me, _ = await _committed_document(engine, "me@retrieval.test")
    retriever = await retriever_with(
        [*_from(other, "theirs"), *_from(me, "mine"), _chunk("a card")],
        {text: _towards(1.0) for text in ("theirs", "mine", "a card")},
        viewer_id=me,
    )

    labels = {doc.page_content: labelled_text(doc) for doc in await retriever.ainvoke("cells")}
    assert labels["theirs"] == "[From another learner's upload, not verified]\ntheirs"
    assert labels["mine"] == "[From your own file]\nmine"
    assert labels["a card"] == "[From a card that passed checks]\na card"


async def test_the_same_passage_is_returned_once(retriever_with):
    retriever = await retriever_with(
        [_chunk("same page", chunk_index=1), _chunk("same page", chunk_index=2), _chunk("other")],
        {"other": _towards(1.0, 0.1)},
    )

    assert sorted(_contents(await retriever.ainvoke("cells"))) == ["other", "same page"]


async def test_the_limit_is_respected_after_repeats_are_removed(retriever_with):
    chunks = [_chunk(f"chunk {number}") for number in range(5)]
    retriever = await retriever_with(chunks, k=2)

    assert len(await retriever.ainvoke("cells")) == 2


async def test_chunks_from_another_embedding_model_are_left_out(retriever_with):
    retriever = await retriever_with([_chunk("old", model="an-older-model")])

    assert await retriever.ainvoke("cells") == []


async def test_a_document_id_narrows_the_search(engine, retriever_with):
    owner, chosen = await _committed_document(engine, "a@retrieval.test")
    _, other = await _committed_document(engine, "b@retrieval.test")
    retriever = await retriever_with(
        [
            _chunk("chosen", document_id=chosen, owner_id=owner),
            _chunk("other", document_id=other),
            _chunk("a card"),
        ],
        document_id=chosen,
    )

    assert _contents(await retriever.ainvoke("cells")) == ["chosen"]


async def test_without_a_document_id_it_searches_everything(engine, retriever_with):
    _, document = await _committed_document(engine, "c@retrieval.test")
    retriever = await retriever_with(
        [_chunk("from a file", document_id=document), _chunk("a card")]
    )

    assert sorted(_contents(await retriever.ainvoke("cells"))) == ["a card", "from a file"]


def test_the_sync_path_says_to_use_async():
    with pytest.raises(NotImplementedError):
        KnowledgeRetriever.model_construct(k=1)._get_relevant_documents("q", run_manager=None)


# --- the tool -----------------------------------------------------------------------------


class StubRetriever:
    def __init__(self, reply):
        self.reply = reply
        self.queries = []

    async def ainvoke(self, query):
        self.queries.append(query)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def run_tool(monkeypatch):
    async def _run_tool(retriever, query="cell cycle"):
        runtime = SimpleNamespace(context=KnowledgeContext(retriever=retriever))
        monkeypatch.setattr(tools, "get_runtime", lambda _: runtime)
        return await search_materials.ainvoke(
            {"name": "search_materials", "args": {"query": query}, "id": "1", "type": "tool_call"}
        )

    return _run_tool


async def test_the_tool_gives_the_text_to_the_model_and_keeps_the_documents(run_tool):
    found = [Document(page_content="Cells divide."), Document(page_content="ATP.")]
    retriever = StubRetriever(found)

    message = await run_tool(retriever)

    assert retriever.queries == ["cell cycle"]
    assert message.content == "<source>\nCells divide.\n</source>\n\n<source>\nATP.\n</source>"
    assert message.artifact == found


async def test_the_tool_says_when_nothing_was_found(run_tool):
    message = await run_tool(StubRetriever([]))

    assert (message.content, message.artifact) == (NOTHING_FOUND, [])


async def test_a_failed_search_doesnt_end_the_run(run_tool):
    message = await run_tool(StubRetriever(AIRateLimited()))

    assert message.content == NOTHING_FOUND


def test_the_model_only_chooses_the_query():
    assert set(search_materials.args) == {"query"}
