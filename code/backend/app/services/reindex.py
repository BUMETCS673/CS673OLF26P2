"""Embedding chunks and cards again with the current model, since search filters by model."""

from collections.abc import Callable

from langchain_core.embeddings import Embeddings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.models import ai_errors
from app.models import Card, KnowledgeChunk

BATCH_SIZE = 100


async def _embed_stale(
    session_factory: async_sessionmaker[AsyncSession],
    embeddings: Embeddings,
    model: str,
    entity: type[KnowledgeChunk] | type[Card],
    text_of: Callable,
) -> int:
    """Each batch commits by itself, so stopping part way loses nothing and a rerun continues."""
    done = 0
    while True:
        async with session_factory() as session:
            rows = list(
                await session.scalars(
                    select(entity)
                    # Also finds cards that have no vector yet.
                    .where(entity.embedding_model.is_distinct_from(model))
                    .limit(BATCH_SIZE)
                )
            )
            if not rows:
                return done
            with ai_errors():
                vectors = await embeddings.aembed_documents([text_of(row) for row in rows])
            for row, vector in zip(rows, vectors, strict=True):
                row.embedding, row.embedding_model = vector, model
            await session.commit()
        done += len(rows)


async def reindex(
    session_factory: async_sessionmaker[AsyncSession], embeddings: Embeddings, model: str
) -> int:
    """How many were embedded. Raises the AI errors from `ai_errors` if embedding fails."""
    chunks = await _embed_stale(
        session_factory, embeddings, model, KnowledgeChunk, lambda chunk: chunk.content
    )
    cards = await _embed_stale(
        session_factory, embeddings, model, Card, lambda card: f"{card.front} {card.back}"
    )
    return chunks + cards
