"""Generating cards with AI: daily caps, running the pipeline, and saving the batch."""

import time
from dataclasses import dataclass

from flask import current_app
from sqlalchemy import func, select

from app.ai.pipeline import (
    PIPELINE_PROMPT_VERSION,
    PipelineRequest,
    run_pipeline,
    worst_case_calls,
)
from app.ai.prompts import (
    DocumentEvidence,
    PromptContext,
    TopicEvidence,
    build_prompt,
)
from app.ai.provider import (
    AIRateLimited,
    AIUnavailable,
    CardDraft,
    Role,
    get_provider,
    is_configured,
    model_name,
)
from app.ai.topics import suggest_deck_topics
from app.extensions import db
from app.models import AiGeneration, Card, Deck, DocumentChunk, utcnow
from app.services.errors import BudgetExceeded, InvalidRequest, NotAvailable
from app.services.materials import search_chunks
from app.services.usage import (
    CAP_WINDOW,
    GENERATE,
    SUGGESTIONS,
    feature_calls,
    record_usage,
    within_model_limits,
)

SUGGEST_CONTEXT = 200             # newest cards sent to the judge and to suggestions
SITE_CAP = "AI generation has hit today's limit for the whole site. Try again later."
NOT_COVERED = "That file doesn't seem to cover this topic. Try another one."

CHUNKS_PER_CARD = 2
MIN_CHUNKS = 6
MAX_CHUNKS = 20


@dataclass(frozen=True)
class GenerationRequest:
    """A validated generate request. Which fields are set depends on `mode`."""

    mode: str
    count: int
    prompt: str | None = None
    file_name: str | None = None
    focus: str | None = None        # file mode: the topic, which is also the search query
    document_id: int | None = None  # file mode: the saved document to search


def _knowledge_base_can_answer() -> bool:
    """Whether a search could find anything. If not, the writer isn't offered the tool."""
    if not is_configured(Role.EMBEDDER):
        return False
    usable = select(DocumentChunk.id).where(
        DocumentChunk.embedding_model == model_name(Role.EMBEDDER)
    )
    return db.session.scalar(select(usable.exists()))


def _chunks_for(count: int) -> int:
    """How many chunks to give the writer: more for more cards, within a budget of tokens."""
    return min(max(count * CHUNKS_PER_CARD, MIN_CHUNKS), MAX_CHUNKS)


def _check_daily_caps(user_id: int, cost: dict[Role, int]) -> None:
    """The learner's generations, then each model's calls, with `cost` for this request.

    `cost` is the most calls this request can make per role.
    """
    since = utcnow() - CAP_WINDOW
    recent = select(func.count()).select_from(AiGeneration).where(AiGeneration.created_at > since)

    limit = current_app.config["AI_DAILY_LIMIT"]
    # A batch with no cards gave the learner nothing, so it doesn't use their allowance.
    learner_recent = recent.where(AiGeneration.user_id == user_id, AiGeneration.empty.is_(False))
    if db.session.scalar(learner_recent) >= limit:
        raise BudgetExceeded(
            f"You've reached the limit of {limit} AI generations in 24 hours. Try again later."
        )
    if not within_model_limits(cost):
        raise BudgetExceeded(SITE_CAP)


def _log(mode: str, count: int, kept: int, model: str, started: float, outcome: str) -> None:
    """One line per request (rule 17): never the prompt, the file, the cards or an error's text."""
    current_app.logger.info(
        "ai_generation mode=%s count=%d kept=%d model=%s ms=%d outcome=%s",
        mode, count, kept, model, (time.monotonic() - started) * 1000, outcome,
    )


def suggest_topics_for_deck(deck: Deck, user_id: int) -> list[str]:
    """Up to 3 topics to learn next, for the learner to pick and generate from."""
    limit = current_app.config["AI_SUGGESTIONS_USER_DAILY_LIMIT"]
    if feature_calls(SUGGESTIONS, user_id) >= limit:
        raise BudgetExceeded(f"You've reached the limit of {limit} suggestions in 24 hours.")
    if not within_model_limits({Role.WRITER: 1}):
        raise BudgetExceeded(SITE_CAP)

    rows = db.session.execute(
        select(Card.front, Card.back)
        .where(Card.deck_id == deck.id)
        .order_by(Card.id.desc())
        .limit(SUGGEST_CONTEXT)
    ).all()
    existing = [CardDraft(front=front, back=back) for front, back in rows]

    writer = None
    try:
        writer = get_provider()
        topics = suggest_deck_topics(deck.name, deck.description, existing, writer)
    except AIRateLimited as e:
        record_usage(SUGGESTIONS, user_id, deck.id, writer)
        db.session.commit()
        raise BudgetExceeded(e.message) from None
    except AIUnavailable as e:
        record_usage(SUGGESTIONS, user_id, deck.id, writer)
        db.session.commit()
        raise NotAvailable(e.message) from None
    record_usage(SUGGESTIONS, user_id, deck.id, writer)
    db.session.commit()
    return topics


def generate_cards(deck: Deck, user_id: int, request: GenerationRequest) -> AiGeneration:
    """Run one generate request, and save its batch as pending candidates."""
    mode, count = request.mode, request.count
    can_search = mode == "prompt" and _knowledge_base_can_answer()
    cost = worst_case_calls(can_search)
    if request.document_id is not None:
        cost[Role.EMBEDDER] = 1
    _check_daily_caps(user_id, cost)

    existing_fronts = db.session.scalars(select(Card.front).where(Card.deck_id == deck.id)).all()
    # The judge checks new cards against these for duplicates.
    rows = db.session.execute(
        select(Card.front, Card.back)
        .where(Card.deck_id == deck.id)
        .order_by(Card.id.desc())
        .limit(SUGGEST_CONTEXT)
    ).all()
    existing = [CardDraft(front=front, back=back) for front, back in rows]

    started = time.monotonic()
    model = "-"
    provider = judge = embedder = search = file_text = None

    def record() -> None:
        record_usage(
            GENERATE, user_id, deck.id, provider, judge, PIPELINE_PROMPT_VERSION, embedder
        )

    try:
        provider = get_provider()
        model = provider.name
        if request.document_id is not None:
            # The topic is the query, so no model call is needed to choose one.
            embedder = get_provider(Role.EMBEDDER)
            found = search_chunks(
                embedder, request.focus, request.document_id, limit=_chunks_for(count)
            )
            if not found:
                record()
                db.session.commit()
                _log(mode, count, 0, model, started, "not_covered")
                raise InvalidRequest(NOT_COVERED, "topic")
            file_text = "\n\n".join(chunk.text for chunk in found)
        elif can_search:
            embedder = get_provider(Role.EMBEDDER)

            def search(query: str) -> list[str]:
                # The whole knowledge base. The model only chooses the query.
                found = search_chunks(embedder, query, limit=_chunks_for(count))
                return [chunk.text for chunk in found]

        context = PromptContext(mode, count, deck.name, deck.description, request.focus)
        built = build_prompt(context, prompt=request.prompt, file_text=file_text)
        # Inside the try, so a missing key answers 503. Only a failed write leaves
        # run_pipeline() as an exception. A failed check or repair still returns cards.
        judge = get_provider(Role.JUDGE)
        result = run_pipeline(
            provider,
            judge,
            PipelineRequest(
                prompt=built,
                prompt_context=context,
                existing_fronts=existing_fronts,
                existing=existing,
                evidence=(
                    DocumentEvidence(request.focus, file_text)
                    if request.document_id is not None
                    else TopicEvidence(request.prompt)
                ),
                search=search,
            ),
        )
        drafts, verification = result.drafts, result.verification
    except AIRateLimited as e:
        # A failed call still spent quota, so it's recorded even though nothing else is saved.
        record()
        db.session.commit()
        _log(mode, count, 0, model, started, "rate_limited")
        raise BudgetExceeded(e.message) from None
    except AIUnavailable as e:
        record()
        db.session.commit()
        _log(mode, count, 0, model, started, "unavailable")
        raise NotAvailable(e.message) from None

    generation = AiGeneration(
        user_id=user_id,
        deck_id=deck.id,
        mode=mode,
        requested_count=count,
        prompt=request.prompt or request.focus,
        source_filename=request.file_name,
        model=model,
        verification=verification,
        empty=not drafts,
        prompt_version=PIPELINE_PROMPT_VERSION,
        candidates=[{"front": d.front, "back": d.back, "status": "pending"} for d in drafts],
    )
    db.session.add(generation)
    record()
    db.session.commit()
    _log(mode, count, len(drafts), model, started, "ok")
    return generation
