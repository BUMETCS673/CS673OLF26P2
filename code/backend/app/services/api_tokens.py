"""Creating, listing and revoking personal access tokens."""

import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.core.security import (
    API_TOKEN_PREFIX,
    LAST_USED_PRECISION,
    hash_token,
    new_api_token,
    token_hashes,
)
from app.models import ApiToken, User, utcnow
from app.repositories.api_tokens import ApiTokenRepository
from app.schemas.api_tokens import ApiTokenCreate, ApiTokenCreated, ApiTokenRead

logger = logging.getLogger(__name__)

TOKEN_NOT_FOUND = "Token not found"
MAX_ACTIVE_TOKENS = 10  # one per tool a person connects leaves plenty of room
TOO_MANY_TOKENS = f"You can have at most {MAX_ACTIVE_TOKENS} tokens. Revoke one you no longer use."


class ApiTokenService:
    def __init__(self, session: AsyncSession, tokens: ApiTokenRepository):
        self.session = session  # one request's transaction so nothing saves until commit
        self.tokens = tokens

    async def create(self, user: User, body: ApiTokenCreate) -> ApiTokenCreated:
        # Step 1: refuse a new token once the user has as many working ones as allowed
        now = utcnow()
        if await self.tokens.count_active(user.id, now) >= MAX_ACTIVE_TOKENS:
            logger.info("api token refused", extra={"user_id": user.id, "reason": "too_many"})
            raise Conflict(TOO_MANY_TOKENS)  # 409 to the client
        # Step 2: make a random token and store only its keyed hash like a session
        token = new_api_token()  # 32 random bytes after the cad_ prefix
        days = body.expires_in_days
        row = await self.tokens.add(
            ApiToken(
                user_id=user.id,
                name=body.name,
                token_hash=hash_token(token),
                expires_at=None if days is None else now + timedelta(days=days),  # None never ends
            )
        )  # the flush gives the row its id
        await self.session.commit()
        logger.info("api token created", extra={"user_id": user.id, "token_id": row.id})
        # Step 3: return the raw token this one time because only its hash is kept
        return ApiTokenCreated(**ApiTokenRead.model_validate(row).model_dump(), token=token)  # 201

    async def list_tokens(self, user: User) -> list[ApiTokenRead]:
        rows = await self.tokens.list_active(user.id, utcnow())  # revoked and expired are left out
        return [ApiTokenRead.model_validate(row) for row in rows]

    async def authenticate(self, token: str) -> tuple[int, int] | None:
        """The token's id and user id. None if it's malformed, unknown, revoked or expired."""
        # Step 1: skip the database for anything that isn't one of our tokens
        if not token.startswith(API_TOKEN_PREFIX):
            logger.info("api token refused", extra={"reason": "malformed"})
            return None
        # Step 2: look it up by hash among the tokens that still work
        now = utcnow()
        hashes = token_hashes(token)  # the current key's hash first, then any old key's
        row = await self.tokens.find_working(hashes, now)  # unique index lookup
        if row is None:
            logger.info("api token refused", extra={"reason": "unknown_revoked_or_expired"})
            return None  # the SDK answers 401
        # Step 3: move a token found under an old key, since it may outlive that key
        changed = row.token_hash != hashes[0]
        if changed:
            await self.tokens.rehash(row.id, hashes[0])
        # Step 4: record the use only when the last one is stale
        if row.last_used_at is None or row.last_used_at < now - LAST_USED_PRECISION:
            await self.tokens.touch(row.id, now)  # an agent's burst of calls writes once
            changed = True
        if changed:
            await self.session.commit()
        return row.id, row.user_id

    async def revoke(self, user: User, token_id: int) -> None:
        # someone else's token answers 404 like a missing one and can't be probed
        if not await self.tokens.revoke(token_id, user.id, utcnow()):
            raise NotFound(TOKEN_NOT_FOUND)  # 404 to the client
        await self.session.commit()
        logger.info("api token revoked", extra={"user_id": user.id, "token_id": token_id})
