"""Queries for OAuth access and refresh tokens."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Row, delete, func, or_, select, update

from app.models import OAuthClient, OAuthToken
from app.repositories.base import ModelRepository


class OAuthTokenRepository(ModelRepository[OAuthToken]):
    async def find_access(self, access_hashes: list[str], now: datetime) -> OAuthToken | None:
        """The pair if its access token still works."""
        return await self.session.scalar(
            select(OAuthToken).where(
                OAuthToken.access_hash.in_(access_hashes),  # the unique index, one probe per key
                OAuthToken.revoked_at.is_(None),
                OAuthToken.access_expires_at > now,
            )
        )

    async def touch(self, token_id: int, now: datetime) -> None:
        await self.session.execute(
            update(OAuthToken).where(OAuthToken.id == token_id).values(last_used_at=now)
        )

    async def get_by_refresh(self, refresh_hashes: list[str]) -> OAuthToken | None:
        """The pair even when revoked or expired. The service needs it to spot a reused token."""
        return await self.session.scalar(
            select(OAuthToken).where(OAuthToken.refresh_hash.in_(refresh_hashes))
        )

    async def delete_expired(self, now: datetime) -> int:
        """Delete pairs whose refresh token has expired and return how many.

        Revoked pairs stay until then so a reused refresh token is still recognised.
        """
        result = await self.session.execute(
            delete(OAuthToken).where(OAuthToken.refresh_expires_at <= now)
        )
        return result.rowcount

    async def connected_apps(self, user_id: int, now: datetime) -> Sequence[Row]:
        """Each client the user has a working pair with, its name and when it last acted."""
        name = OAuthClient.client_info["client_name"].astext  # the name it registered with
        # one grouped query over the user's live pairs joined to the client for its name
        return (
            await self.session.execute(
                select(
                    OAuthToken.client_id,
                    name.label("name"),
                    func.min(OAuthToken.created_at).label("connected_at"),  # the first approval
                    func.max(OAuthToken.last_used_at).label("last_used_at"),
                )
                .join(OAuthClient, OAuthClient.client_id == OAuthToken.client_id)
                .where(
                    OAuthToken.user_id == user_id,  # through the user_id index
                    OAuthToken.revoked_at.is_(None),
                    OAuthToken.refresh_expires_at > now,  # a pair that can still refresh
                )
                .group_by(OAuthToken.client_id, name)
                .order_by(func.min(OAuthToken.created_at))  # oldest connection first
            )
        ).all()

    async def revoke_client(self, user_id: int, client_id: str, now: datetime) -> bool:
        """Revoke every pair this user gave one client. False if none still worked."""
        result = await self.session.execute(
            update(OAuthToken)
            .where(
                OAuthToken.user_id == user_id,  # another user's pairs never match
                OAuthToken.client_id == client_id,
                OAuthToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        return result.rowcount > 0

    async def revoke(self, token_hashes: list[str], now: datetime) -> bool:
        """Revoke the pair holding this access or refresh token. False if none still worked."""
        result = await self.session.execute(
            update(OAuthToken)
            .where(
                # either unique index can find the pair
                or_(
                    OAuthToken.access_hash.in_(token_hashes),
                    OAuthToken.refresh_hash.in_(token_hashes),
                ),
                OAuthToken.revoked_at.is_(None),  # a second revoke of the same pair matches nothing
            )
            .values(revoked_at=now)
        )
        return result.rowcount == 1
