"""Problem card reviews: starting one when a card keeps being forgotten, and applying decisions.

    queued -> pending -> completed
       |
       +----> completed (nothing to recommend, or no budget)
       +----> failed (its job ran out of attempts)
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.checkpoints import discard_threads, open_checkpointer
from app.ai.problem_cards.checks import REPLACING_KINDS
from app.ai.problem_cards.graph import resume_review
from app.ai.tracing import labelled_trace
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.core.settings import Settings
from app.models import Card, Deck, Job, ProblemCardReview, User, utcnow
from app.models.job import REVIEW_PROBLEM_CARDS
from app.models.problem_card_review import COMPLETED, FAILED, PENDING, QUEUED
from app.repositories.cards import CardRepository
from app.repositories.jobs import JobRepository
from app.repositories.problem_cards import ProblemCardRepository
from app.schemas.cards import CardRead
from app.schemas.problem_cards import (
    BAD_DECISIONS,
    REMOVE,
    DecisionsApplied,
    ProblemCardReviewRead,
    ProblemCardSummary,
    ReadyReview,
)

logger = logging.getLogger(__name__)

REVIEW_NOT_FOUND = "Review not found."
REFLAG_AFTER = 2  # lapses until a handled card is flagged again
DISMISS_PAUSE = timedelta(days=7)  # no new review after a learner dismisses a whole one
# A study session often turns up several problem cards, so the job waits for them to gather.
GATHER_DELAY = timedelta(minutes=10)


class ProblemCardService:
    def __init__(
        self,
        session: AsyncSession,
        reviews: ProblemCardRepository,
        cards: CardRepository,
        jobs: JobRepository,
        settings: Settings,
    ):
        self.session = session
        self.reviews = reviews
        self.cards = cards
        self.jobs = jobs
        self.settings = settings

    async def _is_paused(self, deck_id: int) -> bool:
        """Whether the learner dismissed every card in the deck's last review, recently."""
        last = await self.reviews.last_completed(deck_id)
        if last is None or not last.decisions:
            return False
        return (
            all(decision["kind"] is None for decision in last.decisions)
            and last.completed_at > utcnow() - DISMISS_PAUSE
        )

    async def queue_if_flagged(self, card: Card, user_id: int) -> None:
        """Start a review if this answer made the card a problem. The caller commits.

        It commits with the answer itself, so a saved lapse can't miss its review.
        """
        if not self.settings.ai_problem_cards_enabled or card.lapses < card.problem_at_lapses:
            return
        if await self._is_paused(card.deck_id):
            return
        review_id = await self.reviews.add_if_none_active(
            user_id, card.deck_id, str(uuid.uuid4())
        )
        if review_id is None:
            return
        job = await self.jobs.add(
            Job(
                user_id=user_id,
                kind=REVIEW_PROBLEM_CARDS,
                payload={"review_id": review_id},
                retry_at=utcnow() + GATHER_DELAY,
            )
        )
        await self.reviews.update(review_id, job_id=job.id)

    async def _fail_abandoned(self, abandoned: list[ProblemCardReview]) -> None:
        """A job can end without its handler finishing, and only its row says so."""
        now = utcnow()
        for review in abandoned:
            review.status, review.completed_at = FAILED, now
        # They've had their chance, so they stay quiet until they lapse again.
        await self.reviews.mark_cards_handled(
            [card_id for review in abandoned for card_id in review.card_ids or []], REFLAG_AFTER
        )
        await self.session.commit()
        await discard_threads(
            self.settings.database_url, [review.thread_id for review in abandoned]
        )

    async def summary(self, user: User) -> ProblemCardSummary:
        active = await self.reviews.active_for_user(user.id)
        abandoned = [
            item.review for item in active if item.review.status == QUEUED and item.job_failed
        ]
        if abandoned:
            await self._fail_abandoned(abandoned)
        return ProblemCardSummary(
            processing=any(
                item.review.status == QUEUED and not item.job_failed for item in active
            ),
            ready=[
                ReadyReview(
                    review_id=item.review.id,
                    deck_id=item.review.deck_id,
                    deck_name=item.deck_name,
                    card_count=len(item.review.recommendations),
                )
                for item in active
                if item.review.status == PENDING
            ],
        )

    async def pending_for_deck(self, deck: Deck) -> ProblemCardReviewRead | None:
        review = await self.reviews.pending_for_deck(deck.id)
        return ProblemCardReviewRead.model_validate(review) if review else None

    def _check_decisions(self, review: ProblemCardReview, decisions: Sequence[dict]) -> None:
        """Each recommended card exactly once, with an option it actually has."""
        options = {item["card_id"]: item["options"] for item in review.recommendations}
        ids = [decision["card_id"] for decision in decisions]
        if sorted(ids) != sorted(options):
            raise InvalidRequest(BAD_DECISIONS, "decisions")
        for decision in decisions:
            option = decision["option"]
            if type(option) is int and not 0 <= option < len(options[decision["card_id"]]):
                raise InvalidRequest(BAD_DECISIONS, "decisions")

    async def _apply(
        self, review: ProblemCardReview, decisions: Sequence[dict]
    ) -> tuple[list[dict], list[Card]]:
        """Change the deck to match the decisions. New cards start as new, with no lapses."""
        options = {item["card_id"]: item["options"] for item in review.recommendations}
        # A card the learner deleted while the review waited is simply not found here.
        cards = {
            card.id: card
            for card in await self.cards.get_many([item["card_id"] for item in decisions])
            if card.deck_id == review.deck_id
        }
        # Decided in memory first, then written as one insert and one delete for all decisions.
        outcomes: list[tuple[int, str | None, list[Card]]] = []
        removed: list[int] = []
        for decision in decisions:
            card_id, choice = decision["card_id"], decision["option"]
            card = cards.get(card_id)
            kind, new_cards = None, []
            if card is not None and choice == REMOVE:
                kind = REMOVE
                removed.append(card_id)
            elif card is not None and choice is not None:
                option = options[card_id][choice]
                kind = option["kind"]
                new_cards = [
                    Card(
                        deck_id=review.deck_id,
                        front=item["front"],
                        back=item["back"],
                        origin="ai",
                    )
                    for item in option["cards"]
                ]
                if kind in REPLACING_KINDS:
                    removed.append(card_id)
                else:
                    card.problem_at_lapses = card.lapses + REFLAG_AFTER
            elif card is not None:
                card.problem_at_lapses = card.lapses + REFLAG_AFTER
            outcomes.append((card_id, kind, new_cards))

        created = await self.cards.add_many(
            [new for _, _, new_cards in outcomes for new in new_cards]
        )
        await self.cards.delete_many(removed)
        applied = [
            {"card_id": card_id, "kind": kind, "new_card_ids": [new.id for new in new_cards]}
            for card_id, kind, new_cards in outcomes
        ]
        return applied, created

    async def decide(
        self, review_id: int, user: User, decisions: Sequence[dict]
    ) -> DecisionsApplied:
        """The deck commits first, as the record of what happened.

        If that fails, the run is still paused and the learner can retry. If finishing the run
        fails afterward, the deck is already right, and only a leftover checkpoint remains.
        """
        review = await self.reviews.get_owned_locked(review_id, user.id)
        if review is None:
            raise NotFound(REVIEW_NOT_FOUND)
        if review.status != PENDING:
            raise Conflict("This review has already been completed.")
        self._check_decisions(review, decisions)

        applied, created = await self._apply(review, decisions)
        review.decisions = applied
        review.status, review.completed_at = COMPLETED, utcnow()
        if created:
            await self.jobs.queue_card_embedding(user.id, [card.id for card in created])
        await self.session.commit()

        url = self.settings.database_url
        try:
            async with (
                labelled_trace(
                    "problem_card_decision",
                    user.id,
                    deck_id=review.deck_id,
                    review_id=review.id,
                    thread_id=review.thread_id,
                ),
                open_checkpointer(url) as checkpointer,
            ):
                await resume_review(checkpointer, review.thread_id, list(decisions))
        except Exception as error:
            logger.warning("problem_cards outcome=resume_failed type=%s", type(error).__name__)
        await discard_threads(url, [review.thread_id])
        return DecisionsApplied(
            review=ProblemCardReviewRead.model_validate(review),
            cards=[CardRead.model_validate(card) for card in created],
        )
