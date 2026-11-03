"""Queries about the knowledge base. The vector store does the reading and writing of chunks."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import (
    ColumnElement,
    Integer,
    Row,
    exists,
    func,
    literal,
    or_,
    select,
    union_all,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeChunk

# High, because "X is 5" and "X is 7" are also very close. A starting point, to tune.
NEAR_DUPLICATE_SIMILARITY = 0.97

# Remembers whether it was shared, so undoing a hide can't share what never passed its checks.
_HIDE = {
    "shared": False,
    "hidden": True,
    "shared_before_hide": or_(
        KnowledgeChunk.shared.is_(True), KnowledgeChunk.shared_before_hide.is_(True)
    ),
}
_UNHIDE = {
    "shared": KnowledgeChunk.shared_before_hide,
    "hidden": False,
    "shared_before_hide": False,
}


@dataclass(frozen=True)
class HiddenChunk:
    chunk_id: uuid.UUID
    # Who uploaded it, or for a card's copy who first accepted it. Null if neither is known.
    source_user_id: int | None


@dataclass(frozen=True)
class CardMatch:
    chunk_id: str
    accepted_by: int
    similarity: float


class KnowledgeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _nearest_each(
        self, vectors: Sequence[list[float]], conditions: Sequence[ColumnElement[bool]]
    ) -> list[Row | None]:
        """Each vector's nearest chunk, in one round trip, in the order of `vectors`.

        Each vector gets its own `ORDER BY distance LIMIT 1` branch, which is the form that uses
        the HNSW index, so the batch costs one index search per vector and no extra trips.
        """
        branches = []
        for position, vector in enumerate(vectors):
            distance = KnowledgeChunk.embedding.cosine_distance(vector)
            branches.append(
                select(
                    literal(position, Integer).label("position"),
                    KnowledgeChunk.langchain_id,
                    KnowledgeChunk.accepted_by,
                    distance.label("distance"),
                )
                .where(*conditions)
                .order_by(distance)
                .limit(1)
                .subquery()
                .select()
            )
        if not branches:
            return []
        statement = branches[0] if len(branches) == 1 else union_all(*branches)
        found = {row.position: row for row in await self.session.execute(statement)}
        return [found.get(position) for position in range(len(vectors))]

    async def closest_similarities(
        self, vectors: Sequence[list[float]], embedding_model: str
    ) -> list[float | None]:
        """Each vector's similarity to its nearest shared chunk."""
        rows = await self._nearest_each(
            vectors,
            [
                KnowledgeChunk.embedding_model == embedding_model,
                KnowledgeChunk.shared.is_(True),  # a private chunk shouldn't hold back a new card
            ],
        )
        return [None if row is None else 1 - row.distance for row in rows]

    async def closest_cards(
        self, vectors: Sequence[list[float]], embedding_model: str
    ) -> list[CardMatch | None]:
        """Each vector's nearest accepted card copy, shared or not."""
        rows = await self._nearest_each(
            vectors,
            [
                KnowledgeChunk.embedding_model == embedding_model,
                KnowledgeChunk.accepted_by.is_not(None),  # matches the card-copy partial index
            ],
        )
        return [
            None
            if row is None
            else CardMatch(str(row.langchain_id), row.accepted_by, 1 - row.distance)
            for row in rows
        ]

    async def closest_card(self, vector: list[float], embedding_model: str) -> CardMatch | None:
        return (await self.closest_cards([vector], embedding_model))[0]

    async def has_chunks(self, embedding_model: str) -> bool:
        return await self.session.scalar(
            select(
                exists().where(
                    KnowledgeChunk.embedding_model == embedding_model,
                    KnowledgeChunk.shared.is_(True),  # the only chunks a writer's search can find
                )
            )
        )

    async def has_exact_match(
        self, query: str, embedding_model: str, document_id: int | None = None
    ) -> bool:
        """Whether one chunk holds every word of `query`, using the search index's language."""
        conditions = [
            KnowledgeChunk.embedding_model == embedding_model,
            KnowledgeChunk.content_tsv.op("@@")(func.plainto_tsquery("english", query)),
        ]
        if document_id is not None:
            conditions.append(KnowledgeChunk.document_id == document_id)
        else:
            conditions.append(KnowledgeChunk.shared.is_(True))
        return await self.session.scalar(select(exists().where(*conditions)))

    async def mark_shared(self, chunk_ids: Sequence[str]) -> None:
        if chunk_ids:
            await self.session.execute(
                update(KnowledgeChunk)
                .where(
                    KnowledgeChunk.langchain_id.in_([uuid.UUID(id_) for id_ in chunk_ids]),
                    KnowledgeChunk.hidden.is_(False),
                )
                .values(shared=True)
            )

    async def mark_screened(self, chunk_ids: Sequence[str], *, share: bool) -> None:
        """Screening cleared these. If they can't be shared yet, `share_waiting_chunks` does it."""
        if chunk_ids:
            await self.session.execute(
                update(KnowledgeChunk)
                .where(
                    KnowledgeChunk.langchain_id.in_([uuid.UUID(id_) for id_ in chunk_ids]),
                    KnowledgeChunk.hidden.is_(False),
                )
                .values(passed_screening=True, shared=share)
            )

    def _waiting(self, owner_id: int) -> tuple:
        return (
            KnowledgeChunk.owner_id == owner_id,
            KnowledgeChunk.passed_screening.is_(True),
            KnowledgeChunk.shared.is_not(True),
            KnowledgeChunk.hidden.is_(False),
        )

    async def share_waiting_chunks(self, owner_id: int) -> None:
        await self.session.execute(
            update(KnowledgeChunk).where(*self._waiting(owner_id)).values(shared=True)
        )

    async def take_over_card_copy(self, chunk_id: str, user_id: int) -> None:
        """Count `user_id` as the first learner to accept this card's fact."""
        await self.session.execute(
            update(KnowledgeChunk)
            .where(KnowledgeChunk.langchain_id == uuid.UUID(chunk_id))
            .values(accepted_by=user_id)
        )

    async def hide_chunks(self, chunk_ids: Sequence[str]) -> list[HiddenChunk]:
        """The chunks it hid, with who they came from."""
        if not chunk_ids:
            return []
        return await self._hide_where(
            KnowledgeChunk.langchain_id.in_([uuid.UUID(id_) for id_ in chunk_ids])
        )

    async def hide_card_copy(self, card_id: int) -> list[HiddenChunk]:
        return await self._hide_where(KnowledgeChunk.source_card_id == card_id)

    async def _hide_where(self, condition) -> list[HiddenChunk]:
        result = await self.session.execute(
            update(KnowledgeChunk)
            .where(condition)
            .values(_HIDE)
            .returning(
                KnowledgeChunk.langchain_id, KnowledgeChunk.owner_id, KnowledgeChunk.accepted_by
            )
        )
        return [
            HiddenChunk(chunk_id, owner_id if owner_id is not None else accepted_by)
            for chunk_id, owner_id, accepted_by in result.all()
        ]

    async def hide_document(self, document_id: int) -> int:
        """Everything from one upload, in one query. Returns how many chunks changed."""
        result = await self.session.execute(
            update(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document_id)
            .values(_HIDE)
        )
        return result.rowcount

    async def hide_user(self, user_id: int) -> int:
        """Everything one learner uploaded or first accepted, in one query."""
        result = await self.session.execute(
            update(KnowledgeChunk)
            .where(
                or_(KnowledgeChunk.owner_id == user_id, KnowledgeChunk.accepted_by == user_id)
            )
            .values(_HIDE)
        )
        return result.rowcount

    async def unhide_document(self, document_id: int) -> int:
        """Undo a hide, including one from a report. Returns how many chunks changed."""
        result = await self.session.execute(
            update(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document_id, KnowledgeChunk.hidden.is_(True))
            .values(_UNHIDE)
        )
        return result.rowcount

    async def unhide_user(self, user_id: int) -> int:
        """Undo a hide of what one learner uploaded or first accepted."""
        result = await self.session.execute(
            update(KnowledgeChunk)
            .where(
                or_(KnowledgeChunk.owner_id == user_id, KnowledgeChunk.accepted_by == user_id),
                KnowledgeChunk.hidden.is_(True),
            )
            .values(_UNHIDE)
        )
        return result.rowcount
