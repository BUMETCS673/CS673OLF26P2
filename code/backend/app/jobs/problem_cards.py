"""The job that diagnoses a deck's problem cards, then leaves the run paused for the learner.

Failures raise, and the job system retries them. If attempts run out, the review picks that up
from the job's row.
"""

import logging
from datetime import timedelta
from typing import Any

from app.ai.checkpoints import discard_threads, open_checkpointer
from app.ai.models import Role, RunModels, load_chat_model
from app.ai.problem_cards.checks import MAX_SIMILAR_CARDS
from app.ai.problem_cards.context import ProblemCardContext
from app.ai.problem_cards.graph import ReviewOutcome, start_review
from app.ai.usage import RunUsage
from app.core.settings import Settings
from app.jobs.execution import JobContext
from app.models import Job, utcnow
from app.models.job import REVIEW_PROBLEM_CARDS
from app.models.problem_card_review import COMPLETED, PENDING, QUEUED
from app.repositories.cards import CardRepository
from app.repositories.jobs import JobRepository
from app.repositories.problem_cards import ProblemCardRepository
from app.repositories.usage import UsageRepository
from app.services.budget import PROBLEM_CARDS, BudgetService
from app.services.problem_cards import REFLAG_AFTER

logger = logging.getLogger(__name__)

MAX_CARDS_PER_REVIEW = 5  # bounds the size of the one model call
JOB_COST = {Role.WRITER: 1, Role.JUDGE: 1}  # one diagnosis call one check
BUDGET_RETRY_DELAY = timedelta(hours=6)  # budgets cover a rolling 24 hours, so room comes back


async def _models_with_room(
    budget: BudgetService, settings: Settings, user_id: int
) -> RunModels | None:
    """Background work stops early, so it can't use up the quota for learners' own requests."""
    _, models = await budget.limit_reached(  # either limit means wait so which one doesn't matter
        PROBLEM_CARDS,
        user_id,
        JOB_COST,
        user_limit=settings.ai_problem_cards_user_daily_limit,
        site_limit=settings.ai_problem_cards_daily_limit,
        # leaves 9 calls per model untouched for learners waiting on a page
        reserve=settings.ai_problem_cards_model_reserve,
        judged=Role.WRITER,  # the judge must outrank the writer it checks
    )
    return models  # None means no room now


async def _postpone(context: JobContext, review_id: int) -> dict[str, Any]:
    """Run later in a new job, so waiting for budget doesn't use up this job's attempts."""
    async with context.session_factory() as session:
        job = await JobRepository(session).add(  # outbox row with pg_notify sent after commit
            Job(
                user_id=context.user_id,
                kind=REVIEW_PROBLEM_CARDS,
                payload={"review_id": review_id},
                retry_at=utcnow() + BUDGET_RETRY_DELAY,  # not claimable for 6 hours
            )
        )
        await ProblemCardRepository(session).update(review_id, job_id=job.id)  # follow the new job
        await session.commit()  # new job and link together
    logger.info("problem card review postponed", extra={"review_id": review_id})
    return {"review_id": review_id, "postponed": True}  # this job ends done not failed


async def _finish_empty(context: JobContext, review_id: int) -> dict[str, Any]:
    async with context.session_factory() as session:
        await ProblemCardRepository(session).update(  # nothing to diagnose so close the review
            review_id, status=COMPLETED, completed_at=utcnow()
        )
        await session.commit()
    logger.info("problem card review empty", extra={"review_id": review_id})
    return {"review_id": review_id, "recommended": 0}


async def _save(
    context: JobContext, review_id: int, card_ids: list[int], outcome: ReviewOutcome
) -> None:
    recommended = {item["card_id"] for item in outcome.recommendations}  # a set for fast lookups
    async with context.session_factory() as session:
        reviews = ProblemCardRepository(session)
        # Step 1: save the recommendations pausing for the learner if there are any
        await reviews.update(  # one UPDATE for every field
            review_id,
            recommendations=outcome.recommendations,
            shared_cause=outcome.shared_cause,  # one cause behind several cards if found
            verification=outcome.verification,  # the judge's verdict
            status=PENDING if recommended else COMPLETED,  # pending means waiting for decide()
            completed_at=None if recommended else utcnow(),
        )
        # Step 2: quiet the cards that got no recommendation
        # A card with no usable fix gets no suggestion, and stays quiet until it lapses again.
        await reviews.mark_cards_handled(  # one UPDATE for all of them
            [card_id for card_id in card_ids if card_id not in recommended], REFLAG_AFTER
        )
        await session.commit()  # both together


async def review_problem_cards(context: JobContext, settings: Settings) -> dict[str, Any] | None:
    review_id = context.payload["review_id"]
    # Step 1: load the review, check the budget and read the cards in one short session
    async with context.session_factory() as session:
        review = await ProblemCardRepository(session).get(review_id)
        if review is None or review.status != QUEUED:  # deleted, or an earlier attempt finished
            logger.info("problem card review skipped", extra={"review_id": review_id})
            return None  # nothing left to do so the job ends done
        deck_id, thread_id = review.deck_id, review.thread_id  # plain values for later
        budget = BudgetService(UsageRepository(session), settings)
        models = await _models_with_room(budget, settings, context.user_id)
        if models is not None:  # no point reading cards without budget
            cards = CardRepository(session)
            # at or past their lapse limit, most lapses first, at most 5
            flagged = await cards.problem_cards(deck_id, MAX_CARDS_PER_REVIEW)
            # one LATERAL query for each card's nearest deck cards by pgvector cosine distance
            similar = await cards.similar_in_deck([card.id for card in flagged], MAX_SIMILAR_CARDS)
            fronts = await cards.fronts_in_deck(deck_id)  # so new cards can't repeat a front
    # Step 2: wait for budget in a new job or close a review with nothing to diagnose
    if models is None:
        return await _postpone(context, review_id)
    if not flagged:  # the cards were fixed or deleted while the job waited
        return await _finish_empty(context, review_id)

    # Step 3: shape the cards for the prompt and note which ones this review covers
    items = [
        {
            "id": card.id,
            "front": card.front,
            "back": card.back,
            "lapses": card.lapses,  # how often it's been forgotten
            # look-alike cards the usual cause of interference
            "similar": [{"front": row.front, "back": row.back} for row in similar[card.id]],
        }
        for card in flagged
    ]
    card_ids = [card.id for card in flagged]
    async with context.session_factory() as session:
        # saved before the AI runs so a dead job's cards can still be quieted later
        await ProblemCardRepository(session).update(review_id, card_ids=card_ids)
        await session.commit()
    logger.info("problem card review started", extra={"review_id": review_id, "cards": len(items)})

    # Step 4: run the LangGraph review until it pauses for the learner or ends
    usage = RunUsage()  # counts each call's model and tokens
    await context.report({"stage": "diagnosing"})  # live progress to the page
    try:
        # the Postgres checkpointer keeps the paused run through restarts until the learner decides
        async with open_checkpointer(settings.database_url) as checkpointer:
            outcome = await start_review(
                ProblemCardContext(
                    writer=load_chat_model(Role.WRITER, settings, usage, models=models),
                    judge=load_chat_model(Role.JUDGE, settings, usage, models=models),
                    cards=items,
                    existing_fronts=fronts,
                ),
                checkpointer,
                thread_id,  # the run's id made when the review was queued
            )
    finally:
        # Step 5: save what the calls spent even if the run failed
        # A failed run still spent its quota.
        async with context.session_factory() as session:
            BudgetService(UsageRepository(session), settings).record(
                PROBLEM_CARDS, context.user_id, deck_id, usage
            )
            await session.commit()

    # Step 6: save the outcome and drop the checkpoint if the run didn't pause
    await _save(context, review_id, card_ids, outcome)
    if not outcome.recommendations:  # only a paused run needs its checkpoint
        await discard_threads(settings.database_url, [thread_id])
    logger.info(
        "problem card review saved",
        extra={"review_id": review_id, "recommended": len(outcome.recommendations)},
    )
    return {"review_id": review_id, "recommended": len(outcome.recommendations)}  # job result
