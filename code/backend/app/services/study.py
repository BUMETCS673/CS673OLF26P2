"""A study session: which cards are due, and answering one."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.models import User, utcnow
from app.repositories.cards import CardRepository
from app.repositories.decks import DeckRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.users import UserRepository
from app.scheduler import LEARN_AHEAD, CardSchedule, CardState, answer_card
from app.schemas.study import DueCards, ReviewRequest, StudyCardRead
from app.services.cards import CARD_NOT_FOUND
from app.services.decks import DECK_NOT_FOUND
from app.services.problem_cards import ProblemCardService
from app.services.trust import grant_if_earned


def _can_answer(schedule: CardSchedule, now: datetime) -> bool:
    """New cards are always due, and learning cards can be answered up to LEARN_AHEAD early."""
    if schedule.state is CardState.NEW:
        return True
    if schedule.state is CardState.REVIEW:
        return schedule.due_at <= now
    return schedule.due_at <= now + LEARN_AHEAD


class StudyService:
    def __init__(
        self,
        session: AsyncSession,
        decks: DeckRepository,
        cards: CardRepository,
        problem_cards: ProblemCardService,
        knowledge: KnowledgeRepository,
        users: UserRepository,
    ):
        self.session = session
        self.decks = decks
        self.cards = cards
        self.problem_cards = problem_cards
        self.knowledge = knowledge
        self.users = users

    async def due_cards(self, deck_id: int, user: User) -> DueCards:
        if await self.decks.get_owned(deck_id, user.id) is None:
            raise NotFound(DECK_NOT_FOUND)
        now = utcnow()
        due = await self.cards.due_cards(deck_id, now)
        return DueCards(
            **{
                name: [StudyCardRead.build(card, now) for card in cards]
                for name, cards in due.items()
            }
        )

    async def review(self, card_id: int, user: User, body: ReviewRequest) -> StudyCardRead:
        # Locked, so a double click can't answer the same card twice.
        card = await self.cards.get_owned(card_id, user.id, lock=True)
        if card is None:
            raise NotFound(CARD_NOT_FOUND)

        # One clock reading, so the due check and the scheduler agree on "now".
        now = utcnow()
        schedule = card.schedule
        if not _can_answer(schedule, now):
            raise Conflict("Card isn't due yet")

        card.schedule = answer_card(schedule, body.rating, now)
        card.last_reviewed_at = now
        await self.problem_cards.queue_if_flagged(card, user.id)
        if card.state == CardState.REVIEW.value:
            await grant_if_earned(user, card.deck_id, now, self.users, self.knowledge)
        await self.session.commit()
        return StudyCardRead.build(card, now)
