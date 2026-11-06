"""A study session: which cards are due, and answering one."""

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, found
from app.models import Deck, User, utcnow
from app.repositories.cards import CardRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.users import UserRepository
from app.scheduler import LEARN_AHEAD, CardSchedule, CardState, answer_card
from app.schemas.study import DueCards, ReviewRequest, StudyCardRead
from app.services.cards import CARD_NOT_FOUND
from app.services.problem_cards import ProblemCardService
from app.services.trust import grant_if_earned

logger = logging.getLogger(__name__)


def _can_answer(schedule: CardSchedule, now: datetime) -> bool:
    """New cards are always due, and learning cards can be answered up to LEARN_AHEAD early."""
    if schedule.state is CardState.NEW:
        return True  # new cards have no due time yet
    if schedule.state is CardState.REVIEW:
        return schedule.due_at <= now  # review cards only once due with no studying ahead
    # learning and relearning up to 20 minutes early so a session can finish its steps
    return schedule.due_at <= now + LEARN_AHEAD


class StudyService:
    def __init__(
        self,
        session: AsyncSession,
        cards: CardRepository,
        problem_cards: ProblemCardService,
        knowledge: KnowledgeRepository,
        users: UserRepository,
    ):
        self.session = session  # one request's transaction so nothing saves until commit
        self.cards = cards
        self.problem_cards = problem_cards
        self.knowledge = knowledge
        self.users = users

    async def due_cards(self, deck: Deck) -> DueCards:
        # Step 1: read the deck's due cards grouped as learning, review and new
        now = utcnow()  # one clock reading for the query and the interval previews
        due = await self.cards.due_cards(deck.id, now)  # grouped as learning, review and new
        logger.info(
            "due cards read",
            extra={"deck_id": deck.id, **{name: len(cards) for name, cards in due.items()}},
        )
        # Step 2: add each card's next intervals for the rating buttons
        return DueCards(
            **{
                # intervals in seconds per rating shown under each button
                name: [StudyCardRead.build(card, now) for card in cards]
                for name, cards in due.items()
            }
        )  # 200 with the study page's queue

    async def review(self, card_id: int, user: User, body: ReviewRequest) -> StudyCardRead:
        # Step 1: load the card locked so a double click can't answer it twice
        # SELECT ... FOR UPDATE makes a second answer wait then see the new schedule
        card = found(await self.cards.get_owned(card_id, user.id, lock=True), CARD_NOT_FOUND)

        # Step 2: refuse a card that isn't due using one clock reading that the scheduler
        # shares as "now"
        now = utcnow()
        schedule = card.schedule  # state due time interval ease step lapses as one value
        if not _can_answer(schedule, now):
            logger.info("review refused", extra={"card_id": card.id, "reason": "not_due"})
            raise Conflict("Card isn't due yet")  # 409 to the client

        # Step 3: schedule the card's next review from the rating
        before = schedule.state
        # Anki's algorithm pure with no I/O
        card.schedule = answer_card(schedule, body.rating, now)
        card.last_reviewed_at = now

        # Step 4: queue a problem card review if this lapse took the card to its limit
        await self.problem_cards.queue_if_flagged(card, user.id)  # same transaction as the answer

        # Step 5: a card that reached review may earn the learner trust so their cards can
        # join what other learners search
        if card.state == CardState.REVIEW.value:  # only this answer can finish a deck
            await grant_if_earned(user, card.deck_id, now, self.users, self.knowledge)
        await self.session.commit()  # answer, review job and trust saved together
        logger.info(
            "card reviewed",
            extra={
                "card_id": card.id,
                "rating": str(body.rating),
                "from_state": str(before.value),
                "to_state": card.state,
            },
        )
        return StudyCardRead.build(card, now)  # 200 with the card and its next intervals
