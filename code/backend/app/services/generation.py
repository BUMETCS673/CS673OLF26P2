"""Generating cards with AI: daily caps, choosing the path, running it, and saving the batch."""

import time
from dataclasses import dataclass

from flask import current_app
from sqlalchemy import func, select

from app.ai.card_checks import write_cards
from app.ai.chunking import split_text
from app.ai.cleanup import clean_drafts
from app.ai.pipeline import (
    PIPELINE_PROMPT_VERSION,
    PipelineRequest,
    run_pipeline,
    worst_case_calls,
)
from app.ai.prompts import (
    Evidence,
    NoEvidence,
    PdfEvidence,
    PromptContext,
    TextEvidence,
    TopicEvidence,
    build_prompt,
)
from app.ai.provider import (
    AIRateLimited,
    AIUnavailable,
    Attachment,
    CardDraft,
    Role,
    get_provider,
)
from app.extensions import db
from app.models import AiGeneration, Card, Deck, utcnow
from app.services.errors import BudgetExceeded, NotAvailable
from app.services.usage import CAP_WINDOW, GENERATE, record_usage, within_model_limits

SUGGEST_CONTEXT = 200             # newest cards sent to the model in suggest mode
SITE_CAP = "AI generation has hit today's limit for the whole site. Try again later."


@dataclass(frozen=True)
class GenerationRequest:
    """A validated generate request. Which fields are set depends on `mode`."""

    mode: str
    count: int
    prompt: str | None = None
    file_name: str | None = None
    file_text: str | None = None
    attachment: Attachment | None = None
    focus: str | None = None


def _evidence(
    prompt: str | None, file_text: str | None, attachment: Attachment | None, chunks: list[str],
) -> Evidence:
    """What the judge checks cards against, from the fields the request's mode set."""
    if prompt:
        return TopicEvidence(prompt)
    if file_text is not None:
        return TextEvidence(file_text, chunks)
    if attachment is not None:
        return PdfEvidence(attachment)
    return NoEvidence()


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


def generate_cards(deck: Deck, user_id: int, request: GenerationRequest) -> AiGeneration:
    """Run one generate request, and save its batch as pending candidates."""
    mode, count = request.mode, request.count
    use_graph = current_app.config["AI_PIPELINE"] == "graph"
    chunks = split_text(request.file_text) if use_graph and request.file_text else []
    _check_daily_caps(user_id, worst_case_calls(len(chunks)) if use_graph else {Role.WRITER: 1})

    existing_fronts = db.session.scalars(select(Card.front).where(Card.deck_id == deck.id)).all()
    existing = ()
    # The judge checks for duplicates in every mode. build_prompt() still sends these to the
    # writer only in suggest mode.
    if mode == "suggest" or use_graph:
        rows = db.session.execute(
            select(Card.front, Card.back)
            .where(Card.deck_id == deck.id)
            .order_by(Card.id.desc())
            .limit(SUGGEST_CONTEXT)
        ).all()
        existing = [CardDraft(front=front, back=back) for front, back in rows]

    started = time.monotonic()
    model = "-"
    provider = judge = None  # judge stays None on the single-call path

    def record() -> None:
        record_usage(GENERATE, user_id, deck.id, provider, judge, PIPELINE_PROMPT_VERSION)

    try:
        provider = get_provider()
        model = provider.name
        context = PromptContext(mode, count, deck.name, deck.description, request.focus)
        built = build_prompt(
            context,
            prompt=request.prompt,
            file_text=request.file_text,
            attachment=request.attachment,
            existing=existing,
        )
        if use_graph:
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
                    evidence=_evidence(
                        request.prompt, request.file_text, request.attachment, chunks
                    ),
                ),
            )
            drafts, verification = result.drafts, result.verification
        else:
            raw = write_cards(provider, built, count)
            drafts, verification = clean_drafts(raw, count, existing_fronts), None
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
