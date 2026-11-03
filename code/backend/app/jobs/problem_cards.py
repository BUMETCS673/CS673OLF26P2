"""The job that diagnoses a deck's problem cards, then leaves the run paused for the learner.

Failures raise, and the job system retries them. If attempts run out, the review picks that up
from the job's row.
"""

from datetime import timedelta
from typing import Any

from app.ai.checkpoints import discard_threads, open_checkpointer
from app.ai.models import Role, load_chat_model
from app.ai.problem_cards.checks import similar_card_finder
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

MAX_CARDS_PER_REVIEW = 5  # bounds the size of the one model call
JOB_COST = {Role.WRITER: 1, Role.JUDGE: 1}
JOB_CALLS = sum(JOB_COST.values())
BUDGET_RETRY_DELAY = timedelta(hours=6)  # budgets cover a rolling 24 hours, so room comes back


async def _can_run(budget: BudgetService, settings: Settings, user_id: int) -> bool:
    """Background work stops early, so it can't use up the quota for learners' own requests."""
    site, learner = await budget.feature_calls(PROBLEM_CARDS, user_id)
    return (
        site + JOB_CALLS <= settings.ai_problem_cards_daily_limit
        and learner + JOB_CALLS <= settings.ai_problem_cards_user_daily_limit
        and await budget.within_model_limits(
            JOB_COST, reserve=settings.ai_problem_cards_model_reserve
        )
    )


async def _postpone(context: JobContext, review_id: int) -> dict[str, Any]:
    """Run later in a new job, so waiting for budget doesn't use up this job's attempts."""
    async with context.session_factory() as session:
        job = await JobRepository(session).add(
            Job(
                user_id=context.user_id,
                kind=REVIEW_PROBLEM_CARDS,
                payload={"review_id": review_id},
                retry_at=utcnow() + BUDGET_RETRY_DELAY,
            )
        )
        await ProblemCardRepository(session).update(review_id, job_id=job.id)
        await session.commit()
    return {"review_id": review_id, "postponed": True}


async def _finish_empty(context: JobContext, review_id: int) -> dict[str, Any]:
    async with context.session_factory() as session:
        await ProblemCardRepository(session).update(
            review_id, status=COMPLETED, completed_at=utcnow()
        )
        await session.commit()
    return {"review_id": review_id, "recommended": 0}


async def _save(
    context: JobContext, review_id: int, card_ids: list[int], outcome: ReviewOutcome
) -> None:
    recommended = {item["card_id"] for item in outcome.recommendations}
    async with context.session_factory() as session:
        reviews = ProblemCardRepository(session)
        await reviews.update(
            review_id,
            recommendations=outcome.recommendations,
            shared_cause=outcome.shared_cause,
            verification=outcome.verification,
            status=PENDING if recommended else COMPLETED,
            completed_at=None if recommended else utcnow(),
        )
        # A card with no usable fix gets no suggestion, and stays quiet until it lapses again.
        await reviews.mark_cards_handled(
            [card_id for card_id in card_ids if card_id not in recommended], REFLAG_AFTER
        )
        await session.commit()


async def review_problem_cards(context: JobContext, settings: Settings) -> dict[str, Any] | None:
    review_id = context.payload["review_id"]
    async with context.session_factory() as session:
        review = await ProblemCardRepository(session).get(review_id)
        if review is None or review.status != QUEUED:  # deleted, or an earlier attempt finished
            return None
        deck_id, thread_id = review.deck_id, review.thread_id
        budget = BudgetService(UsageRepository(session), settings)
        has_budget = await _can_run(budget, settings, context.user_id)
        if has_budget:
            cards = CardRepository(session)
            flagged = await cards.problem_cards(deck_id, MAX_CARDS_PER_REVIEW)
            deck_cards = [
                {"id": card.id, "front": card.front, "back": card.back}
                for card in await cards.texts_in_deck(deck_id)
            ]
    if not has_budget:
        return await _postpone(context, review_id)
    if not flagged:
        return await _finish_empty(context, review_id)

    items = []
    find_similar = similar_card_finder(deck_cards)
    for card in flagged:
        item = {"id": card.id, "front": card.front, "back": card.back, "lapses": card.lapses}
        items.append({**item, "similar": find_similar(item)})
    card_ids = [card.id for card in flagged]
    async with context.session_factory() as session:
        await ProblemCardRepository(session).update(review_id, card_ids=card_ids)
        await session.commit()

    usage = RunUsage()
    await context.report({"stage": "diagnosing"})
    try:
        async with open_checkpointer(settings.database_url) as checkpointer:
            outcome = await start_review(
                ProblemCardContext(
                    writer=load_chat_model(Role.WRITER, settings, usage),
                    judge=load_chat_model(Role.JUDGE, settings, usage),
                    cards=items,
                    existing_fronts=[card["front"] for card in deck_cards],
                ),
                checkpointer,
                thread_id,
            )
    finally:
        # A failed run still spent its quota.
        async with context.session_factory() as session:
            BudgetService(UsageRepository(session), settings).record(
                PROBLEM_CARDS, context.user_id, deck_id, usage
            )
            await session.commit()

    await _save(context, review_id, card_ids, outcome)
    if not outcome.recommendations:  # only a paused run needs its checkpoint
        await discard_threads(settings.database_url, [thread_id])
    return {"review_id": review_id, "recommended": len(outcome.recommendations)}
