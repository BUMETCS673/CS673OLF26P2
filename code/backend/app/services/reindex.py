"""Embedding chunks and cards again with the current model, since search filters by model."""

import logging
from collections.abc import Callable

from langchain_core.embeddings import Embeddings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.models import ai_errors
from app.models import Card, KnowledgeChunk

logger = logging.getLogger(__name__)

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
    while True:  # until no stale row is left
        async with session_factory() as session:  # a fresh session per batch keeps memory flat
            # Step 1: take the next batch of rows embedded with another model or none yet
            rows = list(
                await session.scalars(
                    select(entity)
                    # IS DISTINCT FROM also matches NULL unlike != so cards with no vector count
                    .where(entity.embedding_model.is_distinct_from(model))
                    .limit(BATCH_SIZE)  # no OFFSET since saved rows drop out of the next query
                )
            )
            if not rows:
                return done
            # Step 2: embed the batch in one call
            with ai_errors():  # vendor errors become ours so the CLI shows a clear message
                # 100 texts per request instead of 100 requests
                vectors = await embeddings.aembed_documents([text_of(row) for row in rows])
            # Step 3: save each vector with the model that made it
            for row, vector in zip(rows, vectors, strict=True):  # strict so a short reply fails
                row.embedding, row.embedding_model = vector, model  # search filters by model
            await session.commit()  # each batch saved alone so a rerun picks up where it stopped
        done += len(rows)
        logger.info("reindex batch saved", extra={"table": entity.__tablename__, "done": done})


async def reindex(
    session_factory: async_sessionmaker[AsyncSession], embeddings: Embeddings, model: str
) -> int:
    """How many were embedded. Raises the AI errors from `ai_errors` if embedding fails."""
    # Step 1: embed the shared knowledge chunks again
    chunks = await _embed_stale(
        session_factory, embeddings, model, KnowledgeChunk, lambda chunk: chunk.content
    )
    # Step 2: then every card
    cards = await _embed_stale(
        # front and back together the same text the card embedding job uses
        session_factory, embeddings, model, Card, lambda card: f"{card.front} {card.back}"
    )
    return chunks + cards  # the CLI prints the total
