"""Queries for users and their sessions."""

from datetime import datetime

from sqlalchemy import ColumnElement, and_, delete, func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Card, ChunkReport, Deck, User, UserSession
from app.scheduler import CardState

# A finished deck has at least this many cards, all graduated to review.
FINISHED_DECK_CARDS = 10
# And at least one card this far apart, which takes reviews on different days to reach.
FINISHED_DECK_INTERVAL_DAYS = 3


def _finished(since: datetime | None) -> list[ColumnElement[bool]]:
    """HAVING conditions over one deck's cards. With `since`, every card was reviewed after it."""
    conditions = [
        func.count() >= FINISHED_DECK_CARDS,
        func.bool_and(Card.state == CardState.REVIEW.value),
        func.max(Card.interval_days) >= FINISHED_DECK_INTERVAL_DAYS,
    ]
    if since is not None:
        conditions.append(
            func.bool_and(and_(Card.last_reviewed_at.is_not(None), Card.last_reviewed_at >= since))
        )
    return conditions


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def is_trusted(self, user_id: int) -> bool:
        trusted_at = await self.trusted_at(user_id)
        return trusted_at is not None

    async def trusted_at(self, user_id: int) -> datetime | None:
        return await self.session.scalar(select(User.trusted_at).where(User.id == user_id))

    async def deck_is_finished(self, deck_id: int, since: datetime | None) -> bool:
        """Reads only this deck's cards, through the `deck_id` index."""
        finished = await self.session.scalar(
            select(literal(True))
            .select_from(Card)
            .where(Card.deck_id == deck_id)
            .having(*_finished(since))
        )
        return finished is True

    async def count_finished_decks(self, user_id: int, since: datetime | None) -> int:
        finished = (
            select(Card.deck_id)
            .join(Deck, Card.deck_id == Deck.id)
            .where(Deck.user_id == user_id)
            .group_by(Card.deck_id)
            .having(*_finished(since))
            .subquery()
        )
        return await self.session.scalar(select(func.count()).select_from(finished))

    async def grant_trust(self, user_id: int, now: datetime) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id, User.trusted_at.is_(None))
            .values(trusted_at=now)
        )

    async def revoke_trust(self, user_id: int, now: datetime) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(trusted_at=None, trust_lost_at=now)
        )

    async def restore_trust(self, user_id: int, now: datetime) -> bool:
        """Undo a wrong loss. Reports from before `now` stop counting, since they predate it."""
        result = await self.session.execute(
            update(User)
            .where(User.id == user_id, User.trust_lost_at.is_not(None))
            .values(trusted_at=now, trust_lost_at=None)
        )
        return result.rowcount == 1

    async def trusted_reporters_against(self, user_id: int, since: datetime) -> int:
        return await self.session.scalar(
            select(func.count(func.distinct(ChunkReport.reporter_id))).where(
                ChunkReport.target_user_id == user_id,
                ChunkReport.reporter_trusted.is_(True),
                ChunkReport.created_at >= since,
            )
        )

    async def get_by_email(self, email: str) -> User | None:
        """`email` must already be normalized, since a query compares it as given."""
        return await self.session.scalar(select(User).where(User.email == email))

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user

    async def delete(self, user_id: int) -> None:
        """The database's cascade removes everything the user owns."""
        await self.session.execute(delete(User).where(User.id == user_id))

    async def get_by_session(self, token_hash: str, now: datetime) -> User | None:
        """The user a live session belongs to."""
        return await self.session.scalar(
            select(User)
            .join(UserSession, UserSession.user_id == User.id)
            .where(UserSession.token_hash == token_hash, UserSession.expires_at > now)
        )

    async def add_session(self, user_session: UserSession) -> None:
        self.session.add(user_session)
        await self.session.flush()

    async def delete_session(self, token_hash: str) -> None:
        await self.session.execute(
            delete(UserSession).where(UserSession.token_hash == token_hash)
        )

    async def delete_expired_sessions(self, user_id: int, now: datetime) -> None:
        await self.session.execute(
            delete(UserSession).where(UserSession.user_id == user_id, UserSession.expires_at <= now)
        )
