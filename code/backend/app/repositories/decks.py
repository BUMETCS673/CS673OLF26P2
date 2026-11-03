"""Queries for decks. Each read takes the user, so someone else's deck is simply not found."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Deck, ProblemCardReview, TutorConversation


class DeckRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_user(self, user_id: int) -> list[Deck]:
        statement = select(Deck).where(Deck.user_id == user_id).order_by(Deck.id)
        return list(await self.session.scalars(statement))

    async def get_owned(self, deck_id: int, user_id: int) -> Deck | None:
        return await self.session.scalar(
            select(Deck).where(Deck.id == deck_id, Deck.user_id == user_id)
        )

    async def add(self, deck: Deck) -> Deck:
        self.session.add(deck)
        await self.session.flush()
        return deck

    async def delete(self, deck_id: int) -> None:
        """The database's cascade removes the deck's cards, reviews and chat."""
        await self.session.execute(delete(Deck).where(Deck.id == deck_id))

    async def graph_thread_ids(self, deck_id: int) -> list[str]:
        """The deck's saved LangGraph runs, which the database's cascade can't reach."""
        reviews = await self.session.scalars(
            select(ProblemCardReview.thread_id).where(
                ProblemCardReview.deck_id == deck_id, ProblemCardReview.thread_id.is_not(None)
            )
        )
        chats = await self.session.scalars(
            select(TutorConversation.thread_id).where(TutorConversation.deck_id == deck_id)
        )
        return [*reviews, *chats]
