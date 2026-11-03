"""Searching the knowledge base, as a LangChain retriever."""

from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from langchain_postgres import PGVectorStore
from langchain_postgres.v2.hybrid_search_config import HybridSearchConfig, reciprocal_rank_fusion
from pydantic import ConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.repositories.knowledge import KnowledgeRepository

MIN_SIMILARITY = 0.5  # a starting point: tune it against real files
OVERFETCH = 3  # extra candidates, because repeats and capped passages get dropped
MAX_PER_OTHER_USER = 3  # how much of one search a single other learner's uploads can fill

OWN_FILE = "own_file"
OTHER_USER = "other_user"
ACCEPTED_CARD = "accepted_card"
_ORIGIN_LABELS = {
    OWN_FILE: "From your own file",
    OTHER_USER: "From another learner's upload, not verified",
    ACCEPTED_CARD: "From a card that passed checks",
}


class KnowledgeRetriever(BaseRetriever):
    """Hybrid search over one embedding model's chunks, or over one document.

    Fusion scores come from rank alone, so they can't say whether anything is actually relevant.
    A vector search checks that first, and a topic the material doesn't cover finds nothing. A
    chunk holding every word of the query also counts, since a very specific term can be in text
    that's otherwise about something else.

    A search across everyone's materials also limits how much one other learner can supply, ranks
    passages uploaded independently by several learners first, and says where each one came from.
    `viewer_id` is whoever the search is for.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    store: PGVectorStore
    engine: AsyncEngine
    embeddings: Embeddings
    embedding_model: str
    document_id: int | None = None
    viewer_id: int | None = None
    k: int = 10

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        raise NotImplementedError("Use ainvoke: the app's database access is async.")

    async def _aget_relevant_documents(self, query: str, **_: Any) -> list[Document]:
        filters: dict[str, Any] = {"embedding_model": self.embedding_model}
        if self.document_id is not None:
            filters["document_id"] = self.document_id
        else:
            filters["shared"] = True  # a learner's own file can be searched before it's screened

        vector = await self.embeddings.aembed_query(query)
        closest = await self.store.asimilarity_search_with_score_by_vector(
            vector, k=1, filter=filters, hybrid_search_config=None
        )
        too_far = not closest or closest[0][1] > 1 - MIN_SIMILARITY
        if too_far and not await self._has_exact_match(query):
            return []

        fetch = self.k * OVERFETCH
        found = await self.store.asimilarity_search_by_vector(
            vector,
            k=fetch,
            filter=filters,
            fts_query=query,
            # A new config each time, because the store writes to the one it's given.
            hybrid_search_config=HybridSearchConfig(
                tsv_column="content_tsv",
                fusion_function=reciprocal_rank_fusion,
                primary_top_k=fetch,
                secondary_top_k=fetch,
            ),
        )
        if self.document_id is not None:
            return _without_repeats(found)[: self.k]
        return _shared_results(found, self.viewer_id)[: self.k]

    async def _has_exact_match(self, query: str) -> bool:
        async with AsyncSession(self.engine) as session:
            return await KnowledgeRepository(session).has_exact_match(
                query, self.embedding_model, self.document_id
            )


def _shared_results(documents: list[Document], viewer_id: int | None) -> list[Document]:
    """Passages in rank order, with limits per source and each one's origin in its metadata."""
    owners: dict[str, set[int]] = {}
    for document in documents:
        owner = document.metadata.get("owner_id")
        passage_owners = owners.setdefault(document.page_content, set())
        if owner is not None:
            passage_owners.add(owner)

    unique = _without_repeats(documents)
    # Stable, so each group stays in rank order. Several accounts could fake this, which is why
    # it only changes the order, and never lets a passage skip the judge.
    unique.sort(key=lambda document: len(owners[document.page_content]) < 2)

    kept = []
    per_owner: dict[int, int] = {}
    for document in unique:
        passage_owners = owners[document.page_content]
        if not passage_owners:
            origin = ACCEPTED_CARD
        elif viewer_id in passage_owners:
            origin = OWN_FILE
        else:
            origin = OTHER_USER
            owner = document.metadata["owner_id"]
            if per_owner.get(owner, 0) >= MAX_PER_OTHER_USER:
                continue
            per_owner[owner] = per_owner.get(owner, 0) + 1
        document.metadata["origin"] = origin
        kept.append(document)
    return kept


def labelled_text(document: Document) -> str:
    """The passage, after a line from our code saying where it came from, if that's known."""
    origin = document.metadata.get("origin")
    if origin is None:
        return document.page_content
    return f"[{_ORIGIN_LABELS[origin]}]\n{document.page_content}"


def is_unverified(labelled: str) -> bool:
    """Whether `labelled_text` marked this as another learner's upload. Its label always comes
    first, so text inside an upload can't fake this or avoid it."""
    return labelled.startswith(f"[{_ORIGIN_LABELS[OTHER_USER]}]\n")


def _without_repeats(documents: list[Document]) -> list[Document]:
    """The same file from two users gives identical chunks, and only one is useful."""
    seen: set[str] = set()
    unique = []
    for document in documents:
        if document.page_content not in seen:
            seen.add(document.page_content)
            unique.append(document)
    return unique
