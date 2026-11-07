"""Queries for registered OAuth clients."""

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update

from app.models import OAuthClient
from app.repositories.base import ModelRepository


class OAuthClientRepository(ModelRepository[OAuthClient]):
    async def get_info(self, client_id: str) -> dict[str, Any] | None:
        return await self.session.scalar(
            select(OAuthClient.client_info).where(OAuthClient.client_id == client_id)
        )

    async def mark_used(self, client_id: str, now: datetime) -> None:
        """Record the first time a client got tokens."""
        await self.session.execute(
            update(OAuthClient)
            .where(OAuthClient.client_id == client_id, OAuthClient.used_at.is_(None))
            .values(used_at=now)
        )

    async def delete_unused(self, registered_before: datetime) -> int:
        """Delete clients that registered before this and never got a token. Returns how many."""
        result = await self.session.execute(
            delete(OAuthClient).where(
                OAuthClient.used_at.is_(None), OAuthClient.created_at < registered_before
            )
        )
        return result.rowcount
