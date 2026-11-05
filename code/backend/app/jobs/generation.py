"""The job that writes a batch of suggested cards for a deck and saves it for review.

A failed run saves no batch, so it doesn't use the learner's allowance, though its calls still
count against each model's limit.
"""

import logging
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

logger = logging.getLogger(__name__)

DECK_GONE = "That deck no longer exists."
NOT_COVERED = "That file doesn't seem to cover this topic. Try another one."
CHUNKS_PER_CARD = 2
MIN_CHUNKS = 6
MAX_CHUNKS = 20  # caps the prompt's size and so its tokens
PENDING = "pending"


@dataclass(frozen=True)  # frozen so the graph can't change the request mid-run
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
    return min(max(count * CHUNKS_PER_CARD, MIN_CHUNKS), MAX_CHUNKS)  # 2 per card 6 to 20


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
    # usage makes search calls count against the budget
    embeddings = load_embeddings(settings, usage)
    model = model_name(Role.EMBEDDER, settings)
    return KnowledgeRetriever(
        # The store only searches by vector here, so only the retriever embeds.
        store=await create_store(engine, embeddings),
        engine=engine,
        # cached query vectors so a repeated search costs no embedding call
        embeddings=with_query_cache(embeddings, cache, model) if cache is not None else embeddings,
        embedding_model=model,  # only chunks embedded with this model can match
        # one file in file mode or None to search everyone's shared chunks
        document_id=document_id,
        viewer_id=viewer_id,  # who the search is for so results are capped per other learner
        k=k,
    )


@asynccontextmanager
async def _card_repository(engine: AsyncEngine) -> AsyncIterator[CardRepository]:
    async with AsyncSession(engine) as session:  # a short session per duplicate check
        yield CardRepository(session)


async def _has_chunks(engine: AsyncEngine, settings: Settings) -> bool:
    async with AsyncSession(engine) as session:
        model = model_name(Role.EMBEDDER, settings)
        return await KnowledgeRepository(session).has_chunks(model)  # EXISTS stops at the first row


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
    if not await _has_chunks(engine, settings):  # skip the tool when the knowledge base is empty
        return None
    try:
        k = chunks_for(request.count)
        return await _build_retriever(
            engine,
            settings,
            usage,
            document_id=None,  # the centralized knowledge base with every learner's shared chunks
            k=k,
            viewer_id=request.owner_id,
            cache=cache,
        )
    except AIUnavailable:  # without an embedder write from the model's own knowledge
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
    # Step 1: search this one file for the chosen topic
    k = chunks_for(request.count)
    retriever = await _build_retriever(
        engine, settings, usage, document_id=request.document_id, k=k, cache=cache
    )
    with ai_errors():  # vendor errors become ours
        found = await retriever.ainvoke(request.topic)  # one embedding call one vector search
    # Step 2: refuse a topic the file doesn't cover so no cards are made up
    if not found:
        raise InvalidRequest(NOT_COVERED, "topic")  # permanent so the job fails with this message
    # Step 3: join the passages and keep their ids for reports later
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
    # Step 1: gather the material for the request's mode
    if request.mode == FILE:
        # file mode finds the passages up front by code and puts them in the prompt
        material, file_chunk_ids = await _file_material(
            request, usage, engine, settings, cache
        )
        body = prompts.file_body(count, name, description, material, request.topic)
        evidence = DocumentEvidence(request.topic, material)  # the judge checks against the text
    else:
        # prompt mode gives the writer a search tool to use when it decides to
        retriever = await _search_for_prompt(request, usage, engine, settings, cache)
        body = prompts.prompt_body(count, name, description, request.prompt)
        evidence = TopicEvidence(request.prompt)  # judged on the topic never on others' uploads

    # Step 2: run the LangGraph card graph which writes, validates, judges and repairs
    outcome = await run_card_graph(
        CardContext(
            writer=load_chat_model(Role.WRITER, settings, usage, models=request.models),
            judge=load_chat_model(Role.JUDGE, settings, usage, models=request.models),
            count=count,
            body=body,
            evidence=evidence,
            # by meaning embedding first and then searching the deck
            find_existing=existing_card_finder(
                request.deck_id, partial(_card_repository, engine), settings, usage, cache=cache
            ),
            existing_fronts=request.existing_fronts,  # exact duplicate check no model call
            retriever=retriever,
        )
    )
    # Step 3: return the cards with the judge's verdict and where they came from
    return CardResult(
        outcome.cards,
        outcome.verification,
        prompts.PROMPT_VERSION,  # saved with the batch to compare prompt changes
        file_chunk_ids or outcome.source_chunk_ids,  # chunks a report would hide
    )


async def _record_usage(
    context: JobContext, settings: Settings, deck_id: int, usage: RunUsage, version: str | None
) -> None:
    async with context.session_factory() as session:
        # The deck may have been deleted during the run, and the spending still counts.
        deck = await DeckRepository(session).get_owned(deck_id, context.user_id)
        BudgetService(UsageRepository(session), settings).record(
            # None for a deleted deck since the usage row's foreign key can't point at it
            GENERATE, context.user_id, deck.id if deck else None, usage, version
        )
        await session.commit()


async def _save(context: JobContext, writer_model: str, deck_id: int, result: CardResult) -> int:
    """Save the batch, once per job, even if two workers both reach this point."""
    payload = context.payload
    async with context.session_factory() as session:
        generations = GenerationRepository(session)
        try:
            # Step 1: insert the batch job_id is UNIQUE so a job can save only one
            generation = await generations.add(
                AiGeneration(
                    job_id=context.job_id,  # the idempotency key
                    user_id=context.user_id,
                    deck_id=deck_id,
                    mode=payload["mode"],
                    requested_count=payload["count"],
                    prompt=payload["prompt"] or payload["topic"],  # whichever the mode used
                    source_filename=payload["file_name"],
                    model=writer_model,
                    verification=result.verification,
                    empty=not result.drafts,  # an empty batch doesn't count toward the daily limit
                    prompt_version=result.prompt_version,
                    source_chunk_ids=result.source_chunk_ids,
                    candidates=[  # JSONB so the learner can accept or reject each one later
                        {"front": draft.front, "back": draft.back, "status": PENDING}
                        for draft in result.drafts
                    ],
                )
            )
            await session.commit()
            return generation.id
        # Step 2: on a unique or foreign key violation check what's saved to tell which
        except IntegrityError:  # another worker saved it, or the deck was deleted
            await session.rollback()  # the failed INSERT spoiled the transaction
            saved = await generations.get_for_job(context.job_id)
            if saved is None:  # not a duplicate so the deck's foreign key failed
                raise NotFound(DECK_GONE) from None  # permanent so the job fails with this
            return saved.id  # the other worker's batch gives the same result with no duplicate


async def generate_cards(
    context: JobContext, settings: Settings, write: CardWriter
) -> dict[str, Any]:
    payload = context.payload
    deck_id = payload["deck_id"]
    # Step 1: in one short session check for an earlier batch load the deck pick models
    async with context.session_factory() as session:
        # An earlier attempt saved its batch, then its worker died before finishing the job.
        saved = await GenerationRepository(session).get_for_job(context.job_id)
        if saved is not None:
            logger.info("generation reused", extra={"generation_id": saved.id})
            return {"generation_id": saved.id}  # no AI calls spent twice
        deck = await DeckRepository(session).get_owned(deck_id, context.user_id)
        if deck is None:  # deleted while the job waited
            raise NotFound(DECK_GONE)  # permanent so no retry
        fronts = await CardRepository(session).fronts_in_deck(deck_id)  # for duplicate checks
        # The service checked for room when queueing. No room here tries each role's chain.
        budget = BudgetService(UsageRepository(session), settings)
        models = await budget.pick_models(WORST_CASE_CALLS, judged=Role.WRITER)
    # the whole chains since the learner was promised a run and fallbacks can handle it
    models = models or first_models(settings, WORST_CASE_CALLS, judged=Role.WRITER)

    # Step 2: build the request from plain values so no ORM object outlives its session
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
    usage = RunUsage()  # callbacks count each call's model and tokens
    version = None
    try:
        # Step 3: write the cards then save the batch
        await context.report({"stage": "writing"})  # live progress to the page
        result = await write(request, usage)  # write_cards with its dependencies bound
        version = result.prompt_version
        writer = models.first(Role.WRITER).name  # the model the run started on
        generation_id = await _save(context, writer, deck_id, result)
        logger.info(
            "generation saved",
            extra={
                "generation_id": generation_id,
                "mode": request.mode,
                "asked": request.count,
                "written": len(result.drafts),
                "verification": result.verification or "none",
            },
        )
        return {"generation_id": generation_id}  # the page reads the batch by this id
    finally:
        # Step 4: save what the calls spent whether the run worked or not
        await _record_usage(context, settings, deck_id, usage, version)
