"""The job that writes a batch of suggested cards for a deck and saves it for review.

A failed run saves no batch, so it doesn't use the learner's allowance, though its calls still
count against each model's limit.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from langchain_core.stores import ByteStore
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.ai.cards import prompts
from app.ai.cards.context import CardContext
from app.ai.cards.existing import existing_card_finder
from app.ai.cards.graph import run_card_graph
from app.ai.judge import DocumentEvidence, TopicEvidence
from app.ai.knowledge.indexing import with_query_cache
from app.ai.knowledge.retrieval import KnowledgeRetriever
from app.ai.knowledge.store import create_store
from app.ai.models import (
    AIUnavailable,
    Role,
    RunModels,
    ai_errors,
    first_models,
    load_chat_model,
    load_embeddings,
    model_name,
)
from app.ai.schemas import CardDraft
from app.ai.usage import RunUsage
from app.core.errors import InvalidRequest, NotFound
from app.core.settings import Settings
from app.jobs.execution import JobContext
from app.models import AiGeneration
from app.repositories.cards import CardRepository
from app.repositories.decks import DeckRepository
from app.repositories.generations import GenerationRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.usage import UsageRepository
from app.schemas.generations import FILE
from app.services.budget import GENERATE, BudgetService
from app.services.generations import WORST_CASE_CALLS

DECK_GONE = "That deck no longer exists."
NOT_COVERED = "That file doesn't seem to cover this topic. Try another one."
CHUNKS_PER_CARD = 2
MIN_CHUNKS = 6
MAX_CHUNKS = 20
PENDING = "pending"


@dataclass(frozen=True)
class CardRequest:
    mode: str
    count: int
    deck_name: str
    deck_description: str | None
    prompt: str | None
    topic: str | None
    document_id: int | None
    owner_id: int
    deck_id: int
    existing_fronts: list[str]
    models: RunModels


@dataclass(frozen=True)
class CardResult:
    drafts: list[CardDraft]
    verification: str | None
    prompt_version: str | None
    source_chunk_ids: list[str] = field(default_factory=list)


CardWriter = Callable[[CardRequest, RunUsage], Awaitable[CardResult]]


def chunks_for(count: int) -> int:
    """How many chunks the writer gets: more for more cards, within a budget of tokens."""
    return min(max(count * CHUNKS_PER_CARD, MIN_CHUNKS), MAX_CHUNKS)


async def _build_retriever(
    engine: AsyncEngine,
    settings: Settings,
    usage: RunUsage,
    *,
    document_id: int | None,
    k: int,
    viewer_id: int | None = None,
    cache: ByteStore | None = None,
) -> KnowledgeRetriever:
    embeddings = load_embeddings(settings, usage)
    model = model_name(Role.EMBEDDER, settings)
    return KnowledgeRetriever(
        # The store only searches by vector here, so only the retriever embeds.
        store=await create_store(engine, embeddings),
        engine=engine,
        embeddings=with_query_cache(embeddings, cache, model) if cache is not None else embeddings,
        embedding_model=model,
        document_id=document_id,
        viewer_id=viewer_id,
        k=k,
    )


@asynccontextmanager
async def _card_repository(engine: AsyncEngine) -> AsyncIterator[CardRepository]:
    async with AsyncSession(engine) as session:
        yield CardRepository(session)


async def _has_chunks(engine: AsyncEngine, settings: Settings) -> bool:
    async with AsyncSession(engine) as session:
        model = model_name(Role.EMBEDDER, settings)
        return await KnowledgeRepository(session).has_chunks(model)


async def _search_for_prompt(
    request: CardRequest,
    usage: RunUsage,
    engine: AsyncEngine,
    settings: Settings,
    cache: ByteStore | None = None,
) -> KnowledgeRetriever | None:
    """A retriever over everyone's materials, if there's anything a search could find.

    Without one the writer simply isn't offered the tool, since prompt mode can work without it.
    """
    if not await _has_chunks(engine, settings):
        return None
    try:
        k = chunks_for(request.count)
        return await _build_retriever(
            engine,
            settings,
            usage,
            document_id=None,
            k=k,
            viewer_id=request.owner_id,
            cache=cache,
        )
    except AIUnavailable:
        return None


async def _file_material(
    request: CardRequest,
    usage: RunUsage,
    engine: AsyncEngine,
    settings: Settings,
    cache: ByteStore | None = None,
) -> tuple[str, list[str]]:
    """The file's passages on the topic and their IDs, found by code, since the learner chose both.

    The topic is the query, so no model call is needed to choose one.
    """
    k = chunks_for(request.count)
    retriever = await _build_retriever(
        engine, settings, usage, document_id=request.document_id, k=k, cache=cache
    )
    with ai_errors():
        found = await retriever.ainvoke(request.topic)
    if not found:
        raise InvalidRequest(NOT_COVERED, "topic")
    material = "\n\n".join(document.page_content for document in found)
    return material, [document.id for document in found if document.id]


async def write_cards(
    request: CardRequest,
    usage: RunUsage,
    engine: AsyncEngine,
    settings: Settings,
    cache: ByteStore | None = None,
) -> CardResult:
    """Set up the card graph for the request's mode, and run it."""
    name, description, count = request.deck_name, request.deck_description, request.count
    retriever = None
    file_chunk_ids: list[str] = []
    if request.mode == FILE:
        material, file_chunk_ids = await _file_material(
            request, usage, engine, settings, cache
        )
        body = prompts.file_body(count, name, description, material, request.topic)
        evidence = DocumentEvidence(request.topic, material)
    else:
        retriever = await _search_for_prompt(request, usage, engine, settings, cache)
        body = prompts.prompt_body(count, name, description, request.prompt)
        evidence = TopicEvidence(request.prompt)

    outcome = await run_card_graph(
        CardContext(
            writer=load_chat_model(Role.WRITER, settings, usage, models=request.models),
            judge=load_chat_model(Role.JUDGE, settings, usage, models=request.models),
            count=count,
            body=body,
            evidence=evidence,
            find_existing=existing_card_finder(
                request.deck_id, partial(_card_repository, engine), settings, usage, cache=cache
            ),
            existing_fronts=request.existing_fronts,
            retriever=retriever,
        )
    )
    return CardResult(
        outcome.cards,
        outcome.verification,
        prompts.PROMPT_VERSION,
        file_chunk_ids or outcome.source_chunk_ids,
    )


async def _record_usage(
    context: JobContext, settings: Settings, deck_id: int, usage: RunUsage, version: str | None
) -> None:
    async with context.session_factory() as session:
        # The deck may have been deleted during the run, and the spending still counts.
        deck = await DeckRepository(session).get_owned(deck_id, context.user_id)
        BudgetService(UsageRepository(session), settings).record(
            GENERATE, context.user_id, deck.id if deck else None, usage, version
        )
        await session.commit()


async def _save(context: JobContext, writer_model: str, deck_id: int, result: CardResult) -> int:
    """Save the batch, once per job, even if two workers both reach this point."""
    payload = context.payload
    async with context.session_factory() as session:
        generations = GenerationRepository(session)
        try:
            generation = await generations.add(
                AiGeneration(
                    job_id=context.job_id,
                    user_id=context.user_id,
                    deck_id=deck_id,
                    mode=payload["mode"],
                    requested_count=payload["count"],
                    prompt=payload["prompt"] or payload["topic"],
                    source_filename=payload["file_name"],
                    model=writer_model,
                    verification=result.verification,
                    empty=not result.drafts,
                    prompt_version=result.prompt_version,
                    source_chunk_ids=result.source_chunk_ids,
                    candidates=[
                        {"front": draft.front, "back": draft.back, "status": PENDING}
                        for draft in result.drafts
                    ],
                )
            )
            await session.commit()
            return generation.id
        except IntegrityError:  # another worker saved it, or the deck was deleted
            await session.rollback()
            saved = await generations.get_for_job(context.job_id)
            if saved is None:
                raise NotFound(DECK_GONE) from None
            return saved.id


async def generate_cards(
    context: JobContext, settings: Settings, write: CardWriter
) -> dict[str, Any]:
    payload = context.payload
    deck_id = payload["deck_id"]
    async with context.session_factory() as session:
        # An earlier attempt saved its batch, then its worker died before finishing the job.
        saved = await GenerationRepository(session).get_for_job(context.job_id)
        if saved is not None:
            return {"generation_id": saved.id}
        deck = await DeckRepository(session).get_owned(deck_id, context.user_id)
        if deck is None:
            raise NotFound(DECK_GONE)
        fronts = await CardRepository(session).fronts_in_deck(deck_id)
        # The service checked for room when queueing. No room here tries each role's chain.
        budget = BudgetService(UsageRepository(session), settings)
        models = await budget.pick_models(WORST_CASE_CALLS, judged=Role.WRITER)
    models = models or first_models(settings, WORST_CASE_CALLS, judged=Role.WRITER)

    request = CardRequest(
        mode=payload["mode"],
        count=payload["count"],
        deck_name=deck.name,
        deck_description=deck.description,
        prompt=payload["prompt"],
        topic=payload["topic"],
        document_id=payload["document_id"],
        owner_id=context.user_id,
        deck_id=deck_id,
        existing_fronts=fronts,
        models=models,
    )
    usage = RunUsage()
    version = None
    try:
        await context.report({"stage": "writing"})
        result = await write(request, usage)
        version = result.prompt_version
        writer = models.first(Role.WRITER).name
        return {"generation_id": await _save(context, writer, deck_id, result)}
    finally:
        await _record_usage(context, settings, deck_id, usage, version)
