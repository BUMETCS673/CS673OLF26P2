"""Discovery, registration, consent, tokens and revoking on Cadence's OAuth server."""

import base64
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select, update

from app.core.redis import get_redis
from app.core.settings import get_settings
from app.jobs.cleanup import clean_oauth
from app.mcp import auth as mcp_auth
from app.mcp.auth import CadenceOAuthProvider
from app.models import OAuthClient, OAuthToken, utcnow

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
STATE = "xyz"


@pytest.fixture(autouse=True)
async def clear_registration_limits():
    """Starts each test at zero because the limit's counters live in Redis for an hour."""
    redis = get_redis()
    keys = [key async for key in redis.scan_iter("oauth:register:*")]
    if keys:
        await redis.delete(*keys)


@pytest.fixture
def oauth_database(monkeypatch, session_factory):
    """Puts the sessions the provider opens inside the test's transaction."""
    monkeypatch.setattr(mcp_auth, "get_session_factory", lambda: session_factory)


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _register(client) -> str:
    resp = await client.post(
        "/register",
        json={
            "client_name": "Claude",
            "redirect_uris": [REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_method": "none",  # a public client, like Claude's
        },
    )
    assert resp.status_code == 201
    return resp.json()["client_id"]


async def _authorize(client, client_id: str, verifier: str) -> str:
    """The consent request's id from where /authorize sends the browser."""
    resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
            "state": STATE,
        },
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "/oauth/consent/" in location
    return location.rsplit("/", 1)[1]


async def _decide(client, request_id: str, approve: bool) -> dict[str, list[str]]:
    resp = await client.post(f"/api/oauth/consent/{request_id}", json={"approve": approve})
    assert resp.status_code == 200
    redirect = urlparse(resp.json()["redirect_url"])
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == REDIRECT
    return parse_qs(redirect.query)


async def _code(client, client_id: str, verifier: str) -> str:
    query = await _decide(client, await _authorize(client, client_id, verifier), approve=True)
    assert query["state"] == [STATE]
    return query["code"][0]


def _swap(client, client_id: str, code: str, verifier: str):
    return client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )


async def _sign_in(client) -> tuple[str, dict]:
    """A registered client and the tokens from a full sign-in."""
    client_id = await _register(client)
    verifier = secrets.token_urlsafe(48)
    resp = await _swap(client, client_id, await _code(client, client_id, verifier), verifier)
    assert resp.status_code == 200
    return client_id, resp.json()


async def _user_of(access_token: str) -> str | None:
    found = await CadenceOAuthProvider().load_access_token(access_token)
    return found.subject if found else None


async def test_the_discovery_files_describe_the_server(client):
    server = (await client.get("/.well-known/oauth-authorization-server")).json()
    resource = (await client.get("/.well-known/oauth-protected-resource/api/mcp")).json()

    assert server["registration_endpoint"].endswith("/register")
    assert server["revocation_endpoint"].endswith("/revoke")
    assert "S256" in server["code_challenge_methods_supported"]
    assert resource["resource"].endswith("/api/mcp")
    assert len(resource["authorization_servers"]) == 1


async def test_a_client_registers_and_is_stored(client, session, oauth_database):
    client_id = await _register(client)

    stored = await session.scalar(select(OAuthClient))
    assert stored.client_id == client_id
    assert stored.client_info["client_name"] == "Claude"


async def test_a_full_sign_in_gives_tokens_that_act_for_the_user(client, me, oauth_database):
    _, tokens = await _sign_in(client)

    assert tokens["token_type"] == "Bearer"
    assert tokens["refresh_token"].startswith("crt_")
    assert await _user_of(tokens["access_token"]) == str(me.id)


async def test_a_code_needs_the_right_verifier_and_works_once(client, me, oauth_database):
    client_id = await _register(client)
    verifier = secrets.token_urlsafe(48)
    code = await _code(client, client_id, verifier)

    wrong = await _swap(client, client_id, code, secrets.token_urlsafe(48))
    first = await _swap(client, client_id, code, verifier)
    again = await _swap(client, client_id, code, verifier)

    assert (wrong.status_code, first.status_code, again.status_code) == (400, 200, 400)
    assert again.json()["error"] == "invalid_grant"


async def test_denying_sends_the_app_an_error_and_ends_the_request(client, me, oauth_database):
    client_id = await _register(client)
    request_id = await _authorize(client, client_id, secrets.token_urlsafe(48))

    query = await _decide(client, request_id, approve=False)

    assert query == {"error": ["access_denied"], "state": [STATE]}
    resp = await client.post(f"/api/oauth/consent/{request_id}", json={"approve": True})
    assert resp.status_code == 404


async def test_a_refresh_replaces_both_tokens(client, me, oauth_database):
    client_id, tokens = await _sign_in(client)

    resp = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": tokens["refresh_token"],
        },
    )

    assert resp.status_code == 200
    assert await _user_of(resp.json()["access_token"]) == str(me.id)
    assert await _user_of(tokens["access_token"]) is None  # the old pair stopped working


async def test_a_reused_refresh_token_revokes_the_whole_chain(client, me, oauth_database):
    client_id, tokens = await _sign_in(client)
    refresh = {"grant_type": "refresh_token", "client_id": client_id}

    first = await client.post("/token", data={**refresh, "refresh_token": tokens["refresh_token"]})
    again = await client.post("/token", data={**refresh, "refresh_token": tokens["refresh_token"]})

    assert (first.status_code, again.status_code) == (200, 400)
    # the copy came back after rotation and even the newest pair is revoked
    assert await _user_of(first.json()["access_token"]) is None


async def test_a_revoked_token_is_refused(client, me, oauth_database):
    client_id, tokens = await _sign_in(client)

    # no client_secret, like Claude and other public clients
    resp = await client.post(
        "/revoke", data={"token": tokens["access_token"], "client_id": client_id}
    )

    assert resp.status_code == 200
    assert await _user_of(tokens["access_token"]) is None


async def test_a_connected_app_is_listed_and_can_be_disconnected(client, me, oauth_database):
    client_id, tokens = await _sign_in(client)

    apps = (await client.get("/api/oauth/apps")).json()
    gone = await client.delete(f"/api/oauth/apps/{client_id}")
    missing = await client.delete(f"/api/oauth/apps/{client_id}")

    assert [(app["client_id"], app["name"]) for app in apps] == [(client_id, "Claude")]
    assert (gone.status_code, missing.status_code) == (204, 404)
    assert (await client.get("/api/oauth/apps")).json() == []
    assert await _user_of(tokens["access_token"]) is None


async def test_registration_is_limited_per_caller(client, oauth_database, monkeypatch):
    monkeypatch.setattr(get_settings(), "oauth_registrations_per_address_hourly", 1)
    await _register(client)

    resp = await client.post(
        "/register", json={"redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none"}
    )

    assert resp.status_code == 429
    assert resp.json()["error"] == "rate_limited"


async def test_cleanup_drops_expired_tokens_and_clients_never_used(
    client, me, session, session_factory, oauth_database
):
    client_id, _ = await _sign_in(client)  # a used client with a live pair
    old = utcnow() - timedelta(days=2)
    session.add(OAuthClient(client_id="abandoned", client_info={}, created_at=old))
    session.add(OAuthClient(client_id="just-registered", client_info={}))
    await session.commit()
    _, expired = await _sign_in(client)
    await session.execute(
        update(OAuthToken)
        .where(OAuthToken.client_id != client_id)
        .values(refresh_expires_at=utcnow() - timedelta(minutes=1))
    )
    await session.commit()

    assert await clean_oauth(session_factory) == (1, 1)

    remaining = set(await session.scalars(select(OAuthClient.client_id)))
    assert "abandoned" not in remaining and {client_id, "just-registered"} <= remaining
    assert await _user_of(expired["access_token"]) is None
