"""Queries for problem card reviews."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Card, Deck, Job, ProblemCardReview
from app.models.job import FAILED as JOB_FAILED
from app.models.problem_card_review import COMPLETED, PENDING, QUEUED


@dataclass(frozen=True)
class ActiveReview:
    review: ProblemCardReview
    deck_name: str
    # Its job ended without the handler finishing, so only this row says the review is over.
    job_failed: bool


class ProblemCardRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_if_none_active(self, user_id: int, deck_id: int, thread_id: str) -> int | None:
        """Start a review, unless the deck has one. The partial unique index decides, atomically."""
        return await self.session.scalar(
            insert(ProblemCardReview)
            .values(user_id=user_id, deck_id=deck_id, thread_id=thread_id, status=QUEUED)
            .on_conflict_do_nothing(
                index_elements=[ProblemCardReview.deck_id],
                index_where=text("status IN ('queued', 'pending')"),
            )
            .returning(ProblemCardReview.id)
        )

    async def get(self, review_id: int) -> ProblemCardReview | None:
        return await self.session.get(ProblemCardReview, review_id)

    async def get_owned_locked(self, review_id: int, user_id: int) -> ProblemCardReview | None:
        """Locked until the commit, so two submissions run one after the other."""
        return await self.session.scalar(
            select(ProblemCardReview)
            .where(ProblemCardReview.id == review_id, ProblemCardReview.user_id == user_id)
            .with_for_update()
        )

    async def update(self, review_id: int, **values: Any) -> None:
        await self.session.execute(
            update(ProblemCardReview).where(ProblemCardReview.id == review_id).values(**values)
        )

    async def last_completed(self, deck_id: int) -> ProblemCardReview | None:
        return await self.session.scalar(
            select(ProblemCardReview)
            .where(ProblemCardReview.deck_id == deck_id, ProblemCardReview.status == COMPLETED)
            .order_by(ProblemCardReview.completed_at.desc())
            .limit(1)
        )

    async def pending_for_deck(self, deck_id: int) -> ProblemCardReview | None:
        return await self.session.scalar(
            select(ProblemCardReview).where(
                ProblemCardReview.deck_id == deck_id, ProblemCardReview.status == PENDING
            )
        )

    async def active_for_user(self, user_id: int) -> list[ActiveReview]:
        """Queued and pending reviews, with what the summary needs, in one query."""
        rows = await self.session.execute(
            select(ProblemCardReview, Deck.name, Job.status)
            .join(Deck, Deck.id == ProblemCardReview.deck_id)
            .outerjoin(Job, Job.id == ProblemCardReview.job_id)
            .where(
                ProblemCardReview.user_id == user_id,
                ProblemCardReview.status.in_((QUEUED, PENDING)),
            )
            .order_by(ProblemCardReview.id)
        )
        return [
            ActiveReview(review, deck_name, job_status == JOB_FAILED)
            for review, deck_name, job_status in rows
        ]

    async def mark_cards_handled(self, card_ids: list[int], reflag_after: int) -> None:
        """Stop flagging these until they lapse again."""
        if card_ids:
            await self.session.execute(
                update(Card)
                .where(Card.id.in_(card_ids))
                .values(problem_at_lapses=Card.lapses + reflag_after)
            )
