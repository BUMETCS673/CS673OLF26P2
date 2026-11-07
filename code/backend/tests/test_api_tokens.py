"""POST, GET and DELETE /api/tokens."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import security
from app.core.security import API_TOKEN_PREFIX, hash_token
from app.core.settings import Settings, get_settings
from app.models import ApiToken, utcnow
from app.repositories.api_tokens import ApiTokenRepository
from app.services import api_tokens as api_tokens_service
from app.services.api_tokens import ApiTokenService


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/api/tokens"), ("post", "/api/tokens"), ("delete", "/api/tokens/1")],
)
async def test_every_route_needs_a_signed_in_user(client, method, path):
    assert (await client.request(method, path)).status_code == 401


async def test_a_new_token_is_shown_once_and_stored_hashed(client, session, me):
    resp = await client.post("/api/tokens", json={"name": "  Claude Desktop "})

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Claude Desktop"
    assert body["token"].startswith(API_TOKEN_PREFIX)
    assert body["last_used_at"] is None
    stored = await session.scalar(select(ApiToken))
    assert stored.token_hash == hash_token(body["token"])
    assert body["token"] not in str((await client.get("/api/tokens")).json())


@pytest.mark.parametrize("name", ["", "   ", "x" * 121])
async def test_a_bad_name_is_422(client, me, name):
    resp = await client.post("/api/tokens", json={"name": name})

    assert resp.status_code == 422
    assert resp.json()["error"]["field"] == "name"


async def test_a_list_has_only_my_working_tokens(client, me, make_user, session):
    other = await make_user(email="other@example.com")
    session.add(ApiToken(user_id=other.id, name="theirs", token_hash="a" * 64))
    await session.commit()
    first = (await client.post("/api/tokens", json={"name": "first"})).json()
    second = (await client.post("/api/tokens", json={"name": "second"})).json()
    await client.delete(f"/api/tokens/{first['id']}")

    resp = await client.get("/api/tokens")

    assert [token["id"] for token in resp.json()] == [second["id"]]


async def test_revoking_keeps_the_row_and_a_second_revoke_is_404(client, session, me):
    token_id = (await client.post("/api/tokens", json={"name": "cli"})).json()["id"]

    first = await client.delete(f"/api/tokens/{token_id}")
    stored = await session.scalar(select(ApiToken))
    second = await client.delete(f"/api/tokens/{token_id}")

    assert first.status_code == 204
    assert stored.revoked_at is not None
    assert second.status_code == 404


async def test_someone_elses_token_is_404_and_stays_working(client, session, me, make_user):
    other = await make_user(email="other@example.com")
    theirs = ApiToken(user_id=other.id, name="theirs", token_hash="b" * 64)
    session.add(theirs)
    await session.commit()

    resp = await client.delete(f"/api/tokens/{theirs.id}")

    assert resp.status_code == 404
    await session.refresh(theirs)
    assert theirs.revoked_at is None


async def test_a_working_token_authenticates_and_records_its_use(client, session, me):
    created = (await client.post("/api/tokens", json={"name": "cli"})).json()
    service = ApiTokenService(session, ApiTokenRepository(session))

    assert await service.authenticate(created["token"]) == (created["id"], me.id)

    stored = await session.scalar(select(ApiToken))
    await session.refresh(stored)
    assert stored.last_used_at is not None


async def test_a_token_moves_to_a_new_key_when_used(client, session, me, monkeypatch):
    created = (await client.post("/api/tokens", json={"name": "cli"})).json()
    service = ApiTokenService(session, ApiTokenRepository(session))
    old_key = get_settings().token_hash_key

    def keys(current: str, old: str = "") -> None:
        new = Settings(token_hash_key=current, token_hash_old_keys=old)
        monkeypatch.setattr(security, "get_settings", lambda: new)

    keys("new-key", old=old_key)  # the rotation keeps the old key for a while
    assert await service.authenticate(created["token"]) == (created["id"], me.id)
    keys("new-key")  # then drops it

    assert await service.authenticate(created["token"]) == (created["id"], me.id)
    stored = await session.scalar(select(ApiToken))
    await session.refresh(stored)
    assert stored.token_hash == hash_token(created["token"])


@pytest.mark.parametrize("revoke", [False, True])
async def test_a_bad_or_revoked_token_doesnt_authenticate(client, session, me, revoke):
    created = (await client.post("/api/tokens", json={"name": "cli"})).json()
    if revoke:
        await client.delete(f"/api/tokens/{created['id']}")
    token = created["token"] if revoke else created["token"].removeprefix(API_TOKEN_PREFIX)
    service = ApiTokenService(session, ApiTokenRepository(session))

    assert await service.authenticate(token) is None


async def test_a_token_expires_in_90_days_unless_told_otherwise(client, me):
    default = (await client.post("/api/tokens", json={"name": "a"})).json()
    never = (await client.post("/api/tokens", json={"name": "b", "expires_in_days": None})).json()

    assert default["expires_at"] is not None
    assert never["expires_at"] is None


@pytest.mark.parametrize("days", [0, 366, "30", True])
async def test_a_bad_expiry_is_422(client, me, days):
    resp = await client.post("/api/tokens", json={"name": "a", "expires_in_days": days})

    assert resp.status_code == 422
    assert resp.json()["error"]["field"] == "expires_in_days"


async def test_an_expired_token_is_hidden_and_doesnt_authenticate(client, session, me):
    created = (await client.post("/api/tokens", json={"name": "old"})).json()
    stored = await session.scalar(select(ApiToken))
    stored.expires_at = utcnow() - timedelta(minutes=1)
    await session.commit()
    service = ApiTokenService(session, ApiTokenRepository(session))

    assert await service.authenticate(created["token"]) is None
    assert (await client.get("/api/tokens")).json() == []


async def test_a_user_can_have_only_so_many_working_tokens(client, me, monkeypatch):
    monkeypatch.setattr(api_tokens_service, "MAX_ACTIVE_TOKENS", 2)
    first = (await client.post("/api/tokens", json={"name": "1"})).json()
    await client.post("/api/tokens", json={"name": "2"})

    refused = await client.post("/api/tokens", json={"name": "3"})
    await client.delete(f"/api/tokens/{first['id']}")
    allowed = await client.post("/api/tokens", json={"name": "3"})

    assert (refused.status_code, allowed.status_code) == (409, 201)
