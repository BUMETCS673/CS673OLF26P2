"""Cadence's OAuth sign-in where a client's request waits for consent and then becomes a code.

Both live in Redis with short expiries because they're only needed for a few minutes. The SDK
has already checked the client and its redirect URI before a request gets here.
"""

import hashlib
import json
import logging
import secrets
import time
from urllib.parse import urlparse

from mcp.server.auth.provider import AuthorizationCode, AuthorizationParams, construct_redirect_uri
from mcp.shared.auth import OAuthClientInformationFull
from redis.asyncio import Redis

from app.core.errors import NotFound
from app.core.settings import Settings
from app.models import User
from app.schemas.oauth import ConsentRead, PendingRequest

logger = logging.getLogger(__name__)

REQUEST_SECONDS = 600  # time to sign in and decide
CODE_SECONDS = 300  # clients swap the code for tokens straight away
REQUEST_NOT_FOUND = "This sign-in request has expired. Start again from your app."


def _request_key(request_id: str) -> str:
    return f"oauth:request:{request_id}"


def _code_key(code: str) -> str:
    # a hash of the code names the key and a Redis dump can't be replayed without the code
    return f"oauth:code:{hashlib.sha256(code.encode()).hexdigest()}"


class OAuthService:
    def __init__(self, redis: Redis, settings: Settings):
        self.redis = redis
        self.settings = settings

    async def start(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Hold the request and return the consent page's URL for the SDK to redirect to."""
        # Step 1: keep what the token step will need under a random id
        request_id = secrets.token_urlsafe(24)  # 192 bits that nobody can guess
        pending = PendingRequest(
            client_id=client.client_id,
            client_name=client.client_name or client.client_id,  # registering a name is optional
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            code_challenge=params.code_challenge,
            scopes=params.scopes or [],
            state=params.state,
            resource=params.resource,
        )
        key = _request_key(request_id)
        await self.redis.set(key, pending.model_dump_json(), ex=REQUEST_SECONDS)  # gone in 10 min
        logger.info("oauth request started", extra={"client_id": client.client_id})
        # Step 2: send the browser to the consent page with the id in its path
        # the login page keeps the path but drops the query when it sends the user back
        return f"{self.settings.public_url}/oauth/consent/{request_id}"

    async def describe(self, request_id: str) -> ConsentRead:
        raw = await self.redis.get(_request_key(request_id))  # read only so the page can reload
        if raw is None:
            raise NotFound(REQUEST_NOT_FOUND)  # 404 to the client once it expired or was answered
        pending = PendingRequest.model_validate_json(raw)
        return ConsentRead(
            client_name=pending.client_name,
            redirect_host=urlparse(pending.redirect_uri).netloc,  # the host the SDK checked
        )

    async def decide(self, request_id: str, user: User, approve: bool) -> str:
        """The URL back to the client with a one-time code if the user approved."""
        # Step 1: take the request out so a second decision on it finds nothing
        raw = await self.redis.getdel(_request_key(request_id))  # GETDEL reads and deletes at once
        if raw is None:
            raise NotFound(REQUEST_NOT_FOUND)  # 404 to the client
        pending = PendingRequest.model_validate_json(raw)
        logger.info(
            "oauth consent decided",
            extra={"user_id": user.id, "client_id": pending.client_id, "approved": approve},
        )
        # Step 2: send a refusal back to the client as an OAuth error
        if not approve:
            return construct_redirect_uri(
                pending.redirect_uri, error="access_denied", state=pending.state
            )  # the frontend sends the browser there

        # Step 3: make a code tied to this user, client and PKCE challenge for the token step
        code = secrets.token_urlsafe(32)  # 256 bits which is above the 160 the spec recommends
        stored = AuthorizationCode(
            code=code,
            scopes=pending.scopes,
            expires_at=time.time() + CODE_SECONDS,
            client_id=pending.client_id,
            code_challenge=pending.code_challenge,
            redirect_uri=pending.redirect_uri,
            redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
            resource=pending.resource,
            subject=str(user.id),  # the user the client's tokens will act for
        )
        await self.redis.set(
            _code_key(code), stored.model_dump_json(exclude={"code"}), ex=CODE_SECONDS
        )  # saved without the code itself
        # Step 4: send the browser back to the client with the code and its state
        return construct_redirect_uri(pending.redirect_uri, code=code, state=pending.state)

    async def load_code(self, client_id: str, code: str) -> AuthorizationCode | None:
        """The code's record if it's still waiting and belongs to this client."""
        raw = await self.redis.get(_code_key(code))
        if raw is None:
            return None  # the SDK answers 400 invalid_grant
        # adds back the code it was saved without
        stored = AuthorizationCode(code=code, **json.loads(raw))
        return stored if stored.client_id == client_id else None  # another client's code is unknown

    async def use_code(self, code: str) -> bool:
        """Delete the code so it works only once. False if it was already used."""
        return await self.redis.delete(_code_key(code)) == 1  # DEL counts the keys it removed
