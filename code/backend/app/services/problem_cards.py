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
from app.core.errors import Conflict, InvalidRequest, found
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
        self.session = session  # one request's transaction so nothing saves until commit
        self.reviews = reviews
        self.cards = cards
        self.jobs = jobs
        self.settings = settings

    async def _is_paused(self, deck_id: int) -> bool:
        """Whether the learner dismissed every card in the deck's last review, recently."""
        # Step 1: no finished review or one with no decisions means no pause
        last = await self.reviews.last_completed(deck_id)
        if last is None or not last.decisions:  # never reviewed or the review failed
            return False
        # Step 2: paused if every card was dismissed within DISMISS_PAUSE
        return (
            # kind None means dismissed
            all(decision["kind"] is None for decision in last.decisions)
            and last.completed_at > utcnow() - DISMISS_PAUSE  # within the last 7 days
        )  # the learner said "not now" so don't nag them

    async def queue_if_flagged(self, card: Card, user_id: int) -> None:
        """Start a review if this answer made the card a problem. The caller commits.

        It commits with the answer itself, so a saved lapse can't miss its review.
        """
        # Step 1: skip unless the feature is on and the card has reached its lapse limit
        # checked first so most answers end here with no query
        if not self.settings.ai_problem_cards_enabled or card.lapses < card.problem_at_lapses:
            return
        # Step 2: skip while the learner's dismissal of the last review still holds
        if await self._is_paused(card.deck_id):  # the card stays flagged for the next review
            logger.info(
                "problem card review skipped", extra={"deck_id": card.deck_id, "reason": "paused"}
            )
            return
        # Step 3: start a review unless the deck already has one under way
        # INSERT ... ON CONFLICT DO NOTHING on a partial unique index keeps one active review
        # per deck with no check-then-insert race
        review_id = await self.reviews.add_if_none_active(
            user_id, card.deck_id, str(uuid.uuid4())  # the thread id for its LangGraph run
        )
        if review_id is None:  # the active review will pick this card up too
            logger.info(
                "problem card review skipped",
                extra={"deck_id": card.deck_id, "reason": "already_active"},
            )
            return
        # Step 4: queue its job delayed so more problem cards from the session can gather
        job = await self.jobs.add(  # an outbox row sent to the queue only after commit
            Job(
                user_id=user_id,
                kind=REVIEW_PROBLEM_CARDS,
                payload={"review_id": review_id},
                # not runnable for 10 minutes so one AI review covers the whole session's cards
                retry_at=utcnow() + GATHER_DELAY,
            )
        )
        await self.reviews.update(review_id, job_id=job.id)  # so a dead job can be detected
        logger.info(
            "problem card review queued",
            extra={"deck_id": card.deck_id, "review_id": review_id, "job_id": job.id},
        )

    async def _fail_abandoned(self, abandoned: list[ProblemCardReview]) -> None:
        """A job can end without its handler finishing, and only its row says so."""
        # Step 1: mark the reviews failed
        now = utcnow()  # one timestamp for all of them
        for review in abandoned:
            review.status, review.completed_at = FAILED, now  # frees the deck for a new review
        # Step 2: their cards have had their chance so they stay quiet until they lapse again
        await self.reviews.mark_cards_handled(  # one UPDATE for every card
            # card_ids is None if the job died before gathering any
            [card_id for review in abandoned for card_id in review.card_ids or []], REFLAG_AFTER
        )
        await self.session.commit()
        # Step 3: drop the reviews' saved LangGraph runs
        await discard_threads(  # after commit and best effort since a leftover is harmless
            self.settings.database_url, [review.thread_id for review in abandoned]
        )
        logger.info("problem card reviews failed", extra={"reviews": len(abandoned)})

    async def summary(self, user: User) -> ProblemCardSummary:
        # Step 1: read the user's active reviews and fail those whose job ran out of attempts
        # one query for each review with its deck's name and whether its job failed
        active = await self.reviews.active_for_user(user.id)
        abandoned = [
            item.review for item in active if item.review.status == QUEUED and item.job_failed
        ]  # a dead job never updates its review so the read path settles it
        if abandoned:
            await self._fail_abandoned(abandoned)
        # Step 2: report whether any are still running and which are ready to decide
        return ProblemCardSummary(  # 200 and the page shows a notice per ready deck
            processing=any(  # the AI is still working on at least one
                item.review.status == QUEUED and not item.job_failed for item in active
            ),
            ready=[  # paused at the learner's decision
                ReadyReview(
                    review_id=item.review.id,
                    deck_id=item.review.deck_id,
                    deck_name=item.deck_name,  # from the join no extra query
                    card_count=len(item.review.recommendations),
                )
                for item in active
                if item.review.status == PENDING
            ],
        )

    async def pending_for_deck(self, deck: Deck) -> ProblemCardReviewRead | None:
        review = await self.reviews.pending_for_deck(deck.id)
        # null when there's none
        return ProblemCardReviewRead.model_validate(review) if review else None

    def _check_decisions(self, review: ProblemCardReview, decisions: Sequence[dict]) -> None:
        """Each recommended card exactly once, with an option it actually has."""
        # Step 1: the decisions must cover the recommended cards each exactly once
        options = {item["card_id"]: item["options"] for item in review.recommendations}
        ids = [decision["card_id"] for decision in decisions]
        # comparing sorted lists catches missing, extra and repeated cards
        if sorted(ids) != sorted(options):
            raise InvalidRequest(BAD_DECISIONS, "decisions")  # 422 and nothing changes
        # Step 2: a numbered option must be one the card was offered
        for decision in decisions:
            option = decision["option"]  # an index, REMOVE or None to dismiss
            # `type is int` because bool is an int in Python so True can't pass as option 1
            if type(option) is int and not 0 <= option < len(options[decision["card_id"]]):
                raise InvalidRequest(BAD_DECISIONS, "decisions")

    async def _apply(
        self, review: ProblemCardReview, decisions: Sequence[dict]
    ) -> tuple[list[dict], list[Card]]:
        """Change the deck to match the decisions. New cards start as new, with no lapses."""
        # Step 1: load the deck's cards being decided and treat a card deleted while the review
        # waited as not found
        options = {item["card_id"]: item["options"] for item in review.recommendations}
        cards = {
            card.id: card
            # one SELECT ... WHERE id IN (...) for every decided card
            for card in await self.cards.get_many([item["card_id"] for item in decisions])
            if card.deck_id == review.deck_id  # only cards still in this deck
        }
        # Step 2: work out each decision in memory first to write them all as one insert and
        # one delete
        outcomes: list[tuple[int, str | None, list[Card]]] = []  # (card, what happened, new cards)
        removed: list[int] = []
        for decision in decisions:
            card_id, choice = decision["card_id"], decision["option"]
            card = cards.get(card_id)  # None if deleted meanwhile which is recorded as dismissed
            kind, new_cards = None, []
            # Removed means the card goes with nothing in its place
            if card is not None and choice == REMOVE:
                kind = REMOVE
                removed.append(card_id)
            # An option adds its new cards while a replacing kind also removes the old card and any
            # other kind keeps it quiet until it lapses REFLAG_AFTER more times
            elif card is not None and choice is not None:
                option = options[card_id][choice]  # the server's stored option not the request
                kind = option["kind"]  # rewrite, split, contrast or prerequisite
                new_cards = [
                    Card(
                        deck_id=review.deck_id,
                        front=item["front"],
                        back=item["back"],
                        origin="ai",
                    )  # new cards start fresh as new with no lapses
                    for item in option["cards"]
                ]
                if kind in REPLACING_KINDS:  # rewrite and split put the new cards in its place
                    removed.append(card_id)
                else:
                    card.problem_at_lapses = card.lapses + REFLAG_AFTER  # 2 more lapses to reflag
            # Dismissed means the card stays as it is quiet until it lapses again
            elif card is not None:
                card.problem_at_lapses = card.lapses + REFLAG_AFTER
            outcomes.append((card_id, kind, new_cards))

        # Step 3: write the new cards and the removals
        created = await self.cards.add_many(  # one multi-row INSERT ... RETURNING for the ids
            [new for _, _, new_cards in outcomes for new in new_cards]
        )
        await self.cards.delete_many(removed)  # one DELETE ... WHERE id IN (...)
        applied = [  # saved on the review as the record of what was done
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
        # Step 1: lock the review and refuse one that's missing, already done or decided
        # wrongly
        # SELECT ... FOR UPDATE makes a double submit wait then see it's completed
        review = found(await self.reviews.get_owned_locked(review_id, user.id), REVIEW_NOT_FOUND)
        if review.status != PENDING:  # decisions apply once
            raise Conflict("This review has already been completed.")  # 409 to the client
        self._check_decisions(review, decisions)  # 422 before anything changes

        # Step 2: change the deck, complete the review and queue the new cards' embedding
        # all in one commit
        applied, created = await self._apply(review, decisions)
        review.decisions = applied
        review.status, review.completed_at = COMPLETED, utcnow()  # frees the deck for a new one
        if created:
            await self.jobs.queue_card_embedding(user.id, [card.id for card in created])
        await self.session.commit()  # the deck is right from here whatever happens below
        logger.info(
            "problem card decisions applied",
            extra={
                "review_id": review.id,
                "decisions": len(applied),
                "removed": sum(1 for item in applied if item["kind"] == REMOVE),
                "dismissed": sum(1 for item in applied if item["kind"] is None),
                "new_cards": len(created),
            },
        )

        # Step 3: finish the paused LangGraph run with the decisions and drop its checkpoints
        # last because the deck is already right if this fails
        url = self.settings.database_url
        try:
            async with (
                labelled_trace(  # the decision shows in LangSmith under the review's run
                    "problem_card_decision",
                    user.id,
                    deck_id=review.deck_id,
                    review_id=review.id,
                    thread_id=review.thread_id,
                ),
                open_checkpointer(url) as checkpointer,  # LangGraph's saved state in Postgres
            ):
                # Command(resume=...) continues the graph from its interrupt() with these
                await resume_review(checkpointer, review.thread_id, list(decisions))
        except Exception as error:  # any failure here can't undo the committed deck
            logger.warning("problem_cards outcome=resume_failed type=%s", type(error).__name__)
        await discard_threads(url, [review.thread_id])  # the run is over so free its checkpoints
        return DecisionsApplied(  # 200 with the completed review and the new cards
            review=ProblemCardReviewRead.model_validate(review),
            cards=[CardRead.model_validate(card) for card in created],
        )
