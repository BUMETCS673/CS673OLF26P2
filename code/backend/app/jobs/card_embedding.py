"""The job that embeds cards, so searches can find them.

Every card gets a vector for searching its own deck. Accepted cards are also copied into the
knowledge base, unless the payload says `"share": false`, which keeps a learner's own cards private.

A copy stays out of shared search until a second learner accepts the same fact. Otherwise one
learner who accepts a false card, or an attacker who accepts their own, could teach it to everyone.

The cards are already saved, so a failure here costs the learner nothing. It only helps later
searches, which is why a full budget skips the work instead of failing.
"""

import math
from typing import Any

from langchain_core.documents import Document as Chunk
from langchain_core.stores import ByteStore
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.knowledge.indexing import create_record_manager, index_chunks, with_embedding_cache
from app.ai.knowledge.store import create_store
from app.ai.models import Role, ai_errors, load_embeddings, model_name
from app.ai.usage import RunUsage
from app.core.settings import Settings
from app.jobs.execution import JobContext
from app.repositories.cards import CardRepository
from app.repositories.knowledge import NEAR_DUPLICATE_SIMILARITY, KnowledgeRepository
from app.repositories.usage import UsageRepository
from app.repositories.users import UserRepository
from app.services.budget import MATERIALS, BudgetService


def _unit(vector: list[float]) -> list[float]:
    """Scaled to length 1 once, so comparing two vectors is a dot product alone."""
    length = math.hypot(*vector)
    return [value / length for value in vector] if length else vector


def _dot(first: list[float], second: list[float]) -> float:
    return math.sumprod(first, second)


def _chunk(card_id: int, text: str, model: str, accepted_by: int) -> Chunk:
    return Chunk(
        page_content=text,
        metadata={
            "embedding_model": model,
            "owner_id": None,
            "accepted_by": accepted_by,
            "document_id": None,
            "chunk_index": None,
            "page": None,
            "source_card_id": card_id,
        },
    )


async def embed_cards(
    context: JobContext, engine: AsyncEngine, settings: Settings, cache: ByteStore
) -> dict[str, Any]:
    async with context.session_factory() as session:
        budget = BudgetService(UsageRepository(session), settings)
        if not await budget.within_model_limits({Role.EMBEDDER: 1}):
            return {"saved": 0}
        # A card deleted since it was accepted has nothing left to add.
        cards = await CardRepository(session).get_many(context.payload["card_ids"])
    if not cards:
        return {"saved": 0}

    usage = RunUsage()
    model = model_name(Role.EMBEDDER, settings)
    embeddings = with_embedding_cache(load_embeddings(settings, usage), cache, model)
    texts = [f"{card.front} {card.back}" for card in cards]
    try:
        with ai_errors():
            vectors = await embeddings.aembed_documents(texts)

        async with context.session_factory() as session:
            await CardRepository(session).save_embeddings(
                {card.id: vector for card, vector in zip(cards, vectors, strict=True)}, model
            )
            await session.commit()
        if not context.payload.get("share", True):
            return {"saved": 0}

        # Checked against the knowledge base, and against this batch's cards kept so far.
        kept: list[tuple[int, str, list[float]]] = []
        async with context.session_factory() as session:
            knowledge = KnowledgeRepository(session)
            users = UserRepository(session)
            trusted = await users.is_trusted(context.user_id)
            # Many cards can match the same learner, so each is looked up once per batch.
            trusted_learners: dict[int, bool] = {}
            confirmed: list[str] = []
            # Two batched searches for the whole job: card copies for every card, then shared
            # chunks only for the cards that aren't copies of an accepted one.
            matches = await knowledge.closest_cards(vectors, model)
            fresh = [
                position
                for position, match in enumerate(matches)
                if match is None or match.similarity < NEAR_DUPLICATE_SIMILARITY
            ]
            closest_shared = dict(
                zip(
                    fresh,
                    await knowledge.closest_similarities([vectors[i] for i in fresh], model),
                    strict=True,
                )
            )
            for position, (card, text, vector, match) in enumerate(
                zip(cards, texts, vectors, matches, strict=True)
            ):
                if position not in closest_shared:
                    # A fact needs two trusted learners. If only this one is, it counts as the
                    # first, so a new account's copy can't block the fact from ever being shared.
                    if trusted and match.accepted_by != context.user_id:
                        if match.accepted_by not in trusted_learners:
                            trusted_learners[match.accepted_by] = await users.is_trusted(
                                match.accepted_by
                            )
                        if trusted_learners[match.accepted_by]:
                            confirmed.append(match.chunk_id)
                        else:
                            await knowledge.take_over_card_copy(match.chunk_id, context.user_id)
                    continue
                closest = closest_shared[position]
                known = closest is not None and closest >= NEAR_DUPLICATE_SIMILARITY
                unit = _unit(vector)
                repeated = any(
                    _dot(unit, other) >= NEAR_DUPLICATE_SIMILARITY for _, _, other in kept
                )
                if not known and not repeated:
                    kept.append((card.id, text, unit))
            await knowledge.mark_shared(confirmed)
            await session.commit()

        # The cache returns these vectors, so saving costs no second call unless Redis is down.
        await index_chunks(
            [_chunk(card_id, text, model, context.user_id) for card_id, text, _ in kept],
            await create_store(engine, embeddings),
            await create_record_manager(engine),
        )
    finally:
        async with context.session_factory() as session:
            BudgetService(UsageRepository(session), settings).record(
                MATERIALS, context.user_id, None, usage
            )
            await session.commit()
    return {"saved": len(kept)}
