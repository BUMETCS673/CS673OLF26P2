"""Queries for personal access tokens."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, func, or_, select, update

from app.models import ApiToken
from app.repositories.base import ModelRepository


def _working(now: datetime) -> list[ColumnElement[bool]]:
    """Not revoked and not past an expiry if it has one."""
    return [
        ApiToken.revoked_at.is_(None),
        or_(ApiToken.expires_at.is_(None), ApiToken.expires_at > now),
    ]


class ApiTokenRepository(ModelRepository[ApiToken]):
    async def list_active(self, user_id: int, now: datetime) -> Sequence[ApiToken]:
        """The user's tokens that still work with the oldest first."""
        return (
            await self.session.scalars(
                select(ApiToken)
                .where(ApiToken.user_id == user_id, *_working(now))
                .order_by(ApiToken.id)
            )
        ).all()

    async def count_active(self, user_id: int, now: datetime) -> int:
        return await self.session.scalar(
            select(func.count()).where(ApiToken.user_id == user_id, *_working(now))
        )

    async def find_working(self, token_hashes: list[str], now: datetime) -> ApiToken | None:
        return await self.session.scalar(
            # the unique index on token_hash finds it with one probe per key
            select(ApiToken).where(ApiToken.token_hash.in_(token_hashes), *_working(now))
        )

    async def rehash(self, token_id: int, token_hash: str) -> None:
        await self.session.execute(
            update(ApiToken).where(ApiToken.id == token_id).values(token_hash=token_hash)
        )

    async def touch(self, token_id: int, now: datetime) -> None:
        await self.session.execute(
            update(ApiToken).where(ApiToken.id == token_id).values(last_used_at=now)
        )

    async def revoke(self, token_id: int, user_id: int, now: datetime) -> bool:
        """False when the token is missing, someone else's or already revoked."""
        # one UPDATE checks ownership and makes the change without a read first
        result = await self.session.execute(
            update(ApiToken)
            .where(
                ApiToken.id == token_id,
                ApiToken.user_id == user_id,
                ApiToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        return result.rowcount == 1
