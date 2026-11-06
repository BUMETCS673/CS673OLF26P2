"""The job that embeds cards, so searches can find them.

Every card gets a vector for searching its own deck. Accepted cards are also copied into the
knowledge base, unless the payload says `"share": false`, which keeps a learner's own cards private.

A copy stays out of shared search until a second learner accepts the same fact. Otherwise one
learner who accepts a false card, or an attacker who accepts their own, could teach it to everyone.

The cards are already saved, so a failure here costs the learner nothing. It only helps later
searches, which is why a full budget skips the work instead of failing.
"""

import logging
import math
from typing import Any

from langchain_core.documents import Document as Chunk
from langchain_core.stores import ByteStore
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.knowledge import same_fact
from app.ai.knowledge.indexing import create_record_manager, index_chunks, with_embedding_cache
from app.ai.knowledge.store import create_store
from app.ai.models import Role, ai_errors, load_chat_model, load_embeddings, model_name
from app.ai.usage import RunUsage
from app.core.settings import Settings
from app.jobs.execution import JobContext
from app.repositories.knowledge import (
    NEAR_DUPLICATE_SIMILARITY,
    SAME_FACT_CANDIDATE,
    CardMatch,
)
from app.services.budget import MATERIALS, BudgetService

logger = logging.getLogger(__name__)


def _unit(vector: list[float]) -> list[float]:
    """Scaled to length 1 once, so comparing two vectors is a dot product alone."""
    length = math.hypot(*vector)  # Euclidean norm in C
    return [value / length for value in vector] if length else vector  # a zero vector stays as is


def _dot(first: list[float], second: list[float]) -> float:
    # for unit vectors this is their cosine similarity computed in C
    return math.sumprod(first, second)


def _chunk(card_id: int, text: str, model: str, accepted_by: int) -> Chunk:
    return Chunk(  # a LangChain Document the shape the PGVector store saves
        page_content=text,
        metadata={
            "embedding_model": model,  # search filters by model so a model change can't mix
            "owner_id": None,  # None since it's not a private file's chunk
            "accepted_by": accepted_by,  # the first learner to accept this fact
            "document_id": None,
            "chunk_index": None,
            "page": None,
            "source_card_id": card_id,  # links the copy back to its card for reports
        },
    )


def _near_copy(match: CardMatch | None) -> bool:
    return match is not None and match.similarity >= NEAR_DUPLICATE_SIMILARITY  # 0.97


async def _same_facts(
    context: JobContext, settings: Settings, usage: RunUsage, pairs: list[tuple[str, str]]
) -> list[bool]:
    """Returns all False when the helper budget is used up."""
    if not pairs:  # no candidates means no model call and no budget query
        return []
    # Step 1: check the helper has room for every batch of pairs
    async with context.transaction() as tx:
        budget = BudgetService(tx.usage, settings)
        calls = math.ceil(len(pairs) / same_fact.BATCH_SIZE)  # 25 pairs per call
        models = await budget.pick_models({Role.HELPER: calls})
        if models is None:
            # without budget treat none as the same fact which is the safe answer
            return [False] * len(pairs)
    # Step 2: ask the helper outside the session so no connection waits on the model
    return await same_fact.same_facts(
        # a factory so each batch gets a fresh model with the fallbacks picked above
        pairs, lambda: load_chat_model(Role.HELPER, settings, usage, models=models)
    )


async def embed_cards(
    context: JobContext, engine: AsyncEngine, settings: Settings, cache: ByteStore
) -> dict[str, Any]:
    # Step 1: check the embedder has room and load the cards that still exist
    async with context.transaction() as tx:
        budget = BudgetService(tx.usage, settings)
        if not await budget.within_model_limits({Role.EMBEDDER: 1}):
            logger.info("card embedding skipped", extra={"reason": "no_budget"})
            # skip instead of failing since the cards are saved and only search loses out
            return {"saved": 0}
        # A card deleted since it was accepted has nothing left to add.
        cards = await tx.cards.get_many(context.payload["card_ids"])  # one IN query
    if not cards:
        return {"saved": 0}

    # Step 2: embed every card in one batch call through the embedding cache
    usage = RunUsage()
    model = model_name(Role.EMBEDDER, settings)
    # CacheBackedEmbeddings reuses vectors from Redis for identical text keyed by SHA-256
    embeddings = with_embedding_cache(load_embeddings(settings, usage), cache, model)
    texts = [f"{card.front} {card.back}" for card in cards]  # front and back as one text
    try:
        with ai_errors():  # vendor errors become ours so the job system can retry or fail
            vectors = await embeddings.aembed_documents(texts)  # one request for the batch

        # Step 3: save each card's vector for searching its own deck
        async with context.transaction() as tx:
            await tx.cards.save_embeddings(  # one bulk UPDATE by primary key
                {card.id: vector for card, vector in zip(cards, vectors, strict=True)}, model
            )
            await tx.commit()
        if not context.payload.get("share", True):  # a learner's own card is never shared
            logger.info("card embedding saved", extra={"cards": len(cards), "shared": 0})
            return {"saved": 0}

        # Step 4: find each card's nearest copy already in the knowledge base
        async with context.transaction() as tx:
            trusted = await tx.users.is_trusted(context.user_id)
            # one round trip with a UNION of per-vector nearest searches on the HNSW index
            matches = await tx.knowledge.closest_cards(vectors, model)
        # Step 5: ask the helper whether close matches state the same fact
        # Only a trusted learner's match to another learner's copy needs the model check.
        candidates = [
            position
            for position, match in enumerate(matches)
            if trusted
            and match is not None
            and match.accepted_by != context.user_id  # matching your own copy confirms nothing
            and match.similarity >= SAME_FACT_CANDIDATE  # 0.95 is close enough to be worth asking
        ]
        # Called outside a session to avoid holding a connection.
        pairs = [(texts[i], matches[i].content) for i in candidates]
        answers = await _same_facts(context, settings, usage, pairs)
        same = dict(zip(candidates, answers, strict=True))  # position -> same fact?
        copies = {  # the model's answer where it was asked else a 0.97 near-copy check
            position
            for position, match in enumerate(matches)
            if same.get(position, _near_copy(match))
        }

        # Step 6: decide whether each card confirms another learner's copy takes it over or
        # stays as a new chunk
        # Checked against the knowledge base, and against this batch's cards kept so far.
        kept: list[tuple[int, str, list[float]]] = []  # (card id, text, unit vector)
        async with context.transaction() as tx:
            knowledge = tx.knowledge
            users = tx.users
            # one IN query for every learner whose copy the model called the same fact
            trusted_learners = await users.trusted_among(
                {match.accepted_by for position, match in enumerate(matches) if same.get(position)}
            )
            confirmed: list[str] = []
            taken_over: list[str] = []  # copies this learner becomes the first acceptor of
            # Maps each card to the copy it confirmed or took over.
            confirmed_by_card: dict[int, str] = {}
            # Only cards that aren't copies are checked against shared chunks.
            fresh = [position for position in range(len(matches)) if position not in copies]
            closest_shared = dict(
                zip(
                    fresh,
                    # one round trip for every fresh card against shared chunks only
                    await knowledge.closest_similarities([vectors[i] for i in fresh], model),
                    strict=True,
                )
            )
            for position, (card, text, vector, match) in enumerate(
                zip(cards, texts, vectors, matches, strict=True)
            ):
                if position in copies:
                    # A fact needs two trusted learners. If only this one is, it counts as the
                    # first, so a new account's copy can't block the fact from ever being shared.
                    if same.get(position):  # the model said same fact
                        confirmed_by_card[card.id] = match.chunk_id
                        if match.accepted_by in trusted_learners:  # a set lookup per card
                            # two trusted learners agree so share it
                            confirmed.append(match.chunk_id)
                        else:
                            taken_over.append(match.chunk_id)
                    continue  # a copy adds no new chunk either way
                closest = closest_shared[position]
                known = closest is not None and closest >= NEAR_DUPLICATE_SIMILARITY  # in KB
                unit = _unit(vector)
                # in-memory check so two near-identical new cards keep only one
                repeated = any(
                    _dot(unit, other) >= NEAR_DUPLICATE_SIMILARITY for _, _, other in kept
                )
                if not known and not repeated:
                    kept.append((card.id, text, unit))
            await knowledge.mark_shared(confirmed)  # one UPDATE for every confirmed chunk
            await knowledge.take_over_card_copies(taken_over, context.user_id)  # one UPDATE
            await tx.cards.save_confirmed_chunks(confirmed_by_card)  # bulk UPDATE
            await tx.commit()

        # Step 7: add the kept cards to the knowledge base as new unshared chunks
        # The cache returns these vectors, so saving costs no second call unless Redis is down.
        await index_chunks(  # LangChain's indexing API whose record manager skips saved chunks
            [_chunk(card_id, text, model, context.user_id) for card_id, text, _ in kept],
            await create_store(engine, embeddings),
            await create_record_manager(engine),
        )
        logger.info(
            "card embedding saved",
            extra={
                "cards": len(cards),
                "same_fact_checks": len(pairs),
                "confirmed": len(confirmed),
                "new_chunks": len(kept),
            },
        )
    finally:
        # Step 8: save what the calls spent even on failure
        async with context.transaction() as tx:
            BudgetService(tx.usage, settings).record(
                MATERIALS, context.user_id, None, usage  # counted under materials' budget
            )
            await tx.commit()
    return {"saved": len(kept)}  # the job's result
