"""Issuing, checking, refreshing and revoking the OAuth tokens Cadence gives to MCP clients."""

import logging
import secrets
from datetime import datetime, timedelta

from mcp.server.auth.provider import AccessToken, RefreshToken
from mcp.shared.auth import OAuthToken as TokenResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.security import LAST_USED_PRECISION, hash_token, token_hashes
from app.models import OAuthToken, User, utcnow
from app.repositories.oauth_clients import OAuthClientRepository
from app.repositories.oauth_tokens import OAuthTokenRepository
from app.schemas.oauth import ConnectedApp

logger = logging.getLogger(__name__)

ACCESS_PREFIX = "cat_"  # tells OAuth tokens apart from the cad_ personal tokens
REFRESH_PREFIX = "crt_"
ACCESS_LIFETIME = timedelta(hours=1)  # short because a refresh gets a new one without the user
REFRESH_LIFETIME = timedelta(days=30)
APP_NOT_FOUND = "App not found"


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())  # the SDK's token models take Unix seconds


class OAuthTokenService:
    def __init__(
        self, session: AsyncSession, tokens: OAuthTokenRepository, clients: OAuthClientRepository
    ):
        self.session = session  # one transaction for each provider call or request
        self.tokens = tokens
        self.clients = clients

    async def issue(
        self, client_id: str, user_id: int, scopes: list[str], resource: str | None
    ) -> TokenResponse:
        """A new access and refresh token pair. Only their hashes are stored."""
        # Step 1: make both tokens from 32 random bytes each
        access = ACCESS_PREFIX + secrets.token_urlsafe(32)
        refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
        # Step 2: save their hashes with both expiry times and mark the client as used
        now = utcnow()
        row = await self.tokens.add(
            OAuthToken(
                user_id=user_id,
                client_id=client_id,
                access_hash=hash_token(access),  # keyed like sessions and personal tokens
                refresh_hash=hash_token(refresh),
                scope=" ".join(scopes),  # space-separated as OAuth writes scopes
                resource=resource,
                access_expires_at=now + ACCESS_LIFETIME,
                refresh_expires_at=now + REFRESH_LIFETIME,
            )
        )
        await self.clients.mark_used(client_id, now)  # cleanup keeps clients that got tokens
        await self.session.commit()  # the pair and the client's mark save together
        logger.info(
            "oauth tokens issued",
            extra={"user_id": user_id, "client_id": client_id, "token_id": row.id},
        )
        # Step 3: hand the raw tokens to the client this one time
        return TokenResponse(
            access_token=access,
            expires_in=int(ACCESS_LIFETIME.total_seconds()),
            scope=row.scope or None,  # left out of the reply when there are no scopes
            refresh_token=refresh,
        )

    async def check_access(self, token: str) -> AccessToken | None:
        """Who an access token acts for. None once it's unknown, expired or revoked."""
        # Step 1: skip the database for anything that isn't one of our access tokens
        if not token.startswith(ACCESS_PREFIX):
            return None
        # Step 2: find the pair among the ones that still work
        now = utcnow()
        row = await self.tokens.find_access(token_hashes(token), now)
        if row is None:
            return None  # the SDK answers 401
        # Step 3: record the use only when the last one is stale
        if row.last_used_at is None or row.last_used_at < now - LAST_USED_PRECISION:
            await self.tokens.touch(row.id, now)  # an agent's burst of calls writes once
            await self.session.commit()
        # Step 4: describe it the way the SDK expects
        return AccessToken(
            token=token,
            client_id=row.client_id,
            scopes=row.scope.split(),
            expires_at=_epoch(row.access_expires_at),
            resource=row.resource,
            subject=str(row.user_id),  # the user the tools act for
        )

    async def find_refresh(self, client_id: str, token: str) -> RefreshToken | None:
        # Step 1: skip the database for anything that isn't one of our refresh tokens
        if not token.startswith(REFRESH_PREFIX):
            return None
        # Step 2: find the pair in any state and check it belongs to the asking client
        row = await self.tokens.get_by_refresh(token_hashes(token))
        if row is None or row.client_id != client_id:  # another client's token reads as unknown
            return None
        # Step 3: treat a retired token as stolen and refuse an expired one
        if row.revoked_at is not None:
            await self._reused(row)
            return None  # the SDK answers 400 invalid_grant
        if row.refresh_expires_at <= utcnow():
            return None
        return RefreshToken(
            token=token,
            client_id=row.client_id,
            scopes=row.scope.split(),
            expires_at=_epoch(row.refresh_expires_at),
            resource=row.resource,
            subject=str(row.user_id),
        )

    async def _reused(self, row: OAuthToken) -> None:
        """Revoke the client's whole chain for this user after a retired refresh token came back.

        A copy of it may be in someone else's hands. OAuth 2.1 says the client has to ask the
        user again.
        """
        if await self.tokens.revoke_client(row.user_id, row.client_id, utcnow()):
            await self.session.commit()
            logger.warning(
                "oauth refresh token reused",
                extra={"user_id": row.user_id, "client_id": row.client_id},
            )

    async def rotate(self, refresh: RefreshToken, scopes: list[str]) -> TokenResponse | None:
        """A new pair in place of this refresh token's. None if it was used already."""
        # Step 1: revoke the old pair which also stops a second refresh with the same token
        if not await self.tokens.revoke(token_hashes(refresh.token), utcnow()):
            return None  # the provider answers 400 invalid_grant
        # Step 2: issue the new pair with the old scopes unless the client asked for fewer
        return await self.issue(
            refresh.client_id, int(refresh.subject), scopes or refresh.scopes, refresh.resource
        )  # the revoke and the new pair commit together

    async def connected_apps(self, user: User) -> list[ConnectedApp]:
        rows = await self.tokens.connected_apps(user.id, utcnow())  # one grouped query
        return [ConnectedApp.model_validate(row, from_attributes=True) for row in rows]

    async def disconnect(self, user: User, client_id: str) -> None:
        """Revoke all of one app's tokens for this user. It has to ask for consent again."""
        if not await self.tokens.revoke_client(user.id, client_id, utcnow()):
            raise NotFound(APP_NOT_FOUND)  # 404 to the client for another user's app too
        await self.session.commit()
        logger.info("oauth app disconnected", extra={"user_id": user.id, "client_id": client_id})

    async def revoke(self, token: str) -> None:
        """Revoke the pair holding this access or refresh token. Unknown tokens are ignored."""
        if await self.tokens.revoke(token_hashes(token), utcnow()):
            await self.session.commit()
            logger.info("oauth tokens revoked")
