"""Auth for the MCP server with Cadence's own OAuth server and personal access tokens.

The SDK's auth middleware checks each Bearer token through the provider and answers 401 for an
unknown one. Tools only ever run for a signed-in user.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthToken as TokenResponse

from app.core.database import get_session_factory
from app.core.redis import get_redis
from app.core.security import API_TOKEN_PREFIX
from app.core.settings import get_settings
from app.models import OAuthClient
from app.repositories.unit_of_work import open_unit_of_work
from app.services.api_tokens import ApiTokenService
from app.services.oauth import OAuthService
from app.services.oauth_tokens import OAuthTokenService


class ApiTokenVerifier:
    """Checks a personal access token and says which user it acts for."""

    async def verify_token(self, token: str) -> AccessToken | None:
        # Step 1: look the token up in a session of its own
        async with open_unit_of_work(get_session_factory()) as tx:  # outside FastAPI's dependencies
            found = await ApiTokenService(tx.session, tx.api_tokens).authenticate(token)
        if found is None:
            return None  # the SDK answers 401
        # Step 2: describe it the way the SDK expects
        token_id, user_id = found
        return AccessToken(
            token=token,
            client_id=f"api-token-{token_id}",  # each token counts as its own client
            scopes=[],
            subject=str(user_id),  # the user the tools act for
        )


class CadenceOAuthProvider:
    """The SDK's OAuthAuthorizationServerProvider that lets Claude or ChatGPT connect over OAuth.

    The SDK serves the endpoints and checks the protocol such as PKCE and redirect URIs. This
    class stores what it hands over. Clients and tokens go to Postgres. Sign-in requests and
    codes go to Redis because they only live for minutes.
    """

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with open_unit_of_work(get_session_factory()) as tx:
            info = await tx.oauth_clients.get_info(client_id)
        return OAuthClientInformationFull.model_validate(info) if info else None  # None is 401

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # Registration is open to anyone as MCP clients expect. A client still can't act for a
        # user until that user approves it on the consent page.
        async with open_unit_of_work(get_session_factory()) as tx:
            await tx.oauth_clients.add(
                OAuthClient(
                    client_id=client_info.client_id,  # a UUID the SDK made
                    client_info=client_info.model_dump(mode="json", exclude_none=True),
                )
            )
            await tx.commit()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        # the SDK redirects the browser to the consent page this returns
        return await self._codes().start(client, params)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        # the SDK checks the code's expiry, redirect URI and PKCE verifier after this
        return await self._codes().load_code(client.client_id, authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> TokenResponse:
        # Step 1: delete the code first so two requests racing with it can't both get tokens
        if not await self._codes().use_code(authorization_code.code):
            raise TokenError("invalid_grant", "authorization code was already used")  # 400
        # Step 2: issue an access and refresh token pair for the user who approved
        async with self._tokens() as tokens:
            return await tokens.issue(
                client.client_id,
                int(authorization_code.subject),  # the user id saved at consent
                authorization_code.scopes,
                authorization_code.resource,
            )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        async with self._tokens() as tokens:
            return await tokens.find_refresh(client.client_id, refresh_token)  # None is 400

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> TokenResponse:
        async with self._tokens() as tokens:
            response = await tokens.rotate(refresh_token, scopes)  # retires the old pair
        if response is None:  # another request with the same refresh token got there first
            raise TokenError("invalid_grant", "refresh token was already used")  # 400
        return response

    async def load_access_token(self, token: str) -> AccessToken | None:
        # The SDK takes a provider or a token verifier but not both. Personal access tokens are
        # checked here too and told apart by their prefix.
        if token.startswith(API_TOKEN_PREFIX):
            return await ApiTokenVerifier().verify_token(token)
        async with self._tokens() as tokens:
            return await tokens.check_access(token)  # None makes the SDK answer 401

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        # the SDK only passes the asking client's own tokens and never a personal token
        async with self._tokens() as tokens:
            await tokens.revoke(token.token)  # revokes both tokens of the pair

    @staticmethod
    def _codes() -> OAuthService:
        return OAuthService(get_redis(), get_settings())

    @staticmethod
    @asynccontextmanager
    async def _tokens() -> AsyncIterator[OAuthTokenService]:
        # the SDK calls these outside FastAPI's dependencies so each call opens its own session
        async with open_unit_of_work(get_session_factory()) as tx:
            yield OAuthTokenService(tx.session, tx.oauth_tokens, tx.oauth_clients)


def current_user_id() -> int:
    """The user behind this tool call. Only valid inside a tool."""
    access = get_access_token()  # set for each request by the SDK's auth middleware
    if access is None or access.subject is None:
        # the auth middleware makes this impossible so it fails loudly if it ever happens
        raise RuntimeError("MCP tool called without an authenticated user")
    return int(access.subject)
