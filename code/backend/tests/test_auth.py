"""POST /api/auth/register, /login and /logout, and GET /me."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.security import hash_session_token
from app.models import User, UserSession, utcnow

EMAIL = "miles@bu.edu"
PASSWORD = "correct horse"


def _register(client, email=EMAIL, password=PASSWORD, **extra):
    return client.post(
        "/api/auth/register", json={"email": email, "password": password, **extra}
    )


def _login(client, email=EMAIL, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _error(resp):
    return resp.json()["error"]


async def test_registering_returns_the_user_and_signs_them_in(client):
    resp = await _register(client, display_name="  Miles ")

    assert resp.status_code == 201
    body = resp.json()
    assert (body["email"], body["display_name"]) == (EMAIL, "Miles")
    assert body["created_at"].endswith("Z")
    assert "password" not in str(body)
    assert (await client.get("/api/auth/me")).json()["id"] == body["id"]


async def test_the_cookie_is_http_only_and_same_site(client):
    resp = await _register(client)

    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


async def test_the_password_and_token_are_only_stored_hashed(client, session):
    resp = await _register(client)

    user = await session.scalar(select(User))
    assert PASSWORD not in user.password_hash
    token = resp.cookies["session"]
    stored = await session.scalar(select(UserSession))
    assert stored.token_hash == hash_session_token(token)
    assert stored.token_hash != token


async def test_an_email_is_normalized(client):
    resp = await _register(client, email="  Miles@BU.edu ")

    assert resp.json()["email"] == EMAIL


async def test_a_second_registration_is_409_in_any_case(client):
    await _register(client)

    resp = await _register(client, email="MILES@BU.EDU")

    assert resp.status_code == 409
    assert _error(resp)["code"] == "conflict"


@pytest.mark.parametrize(
    ("body", "field", "message"),
    [
        ({"password": PASSWORD}, "email", "email is required."),
        ({"email": 7, "password": PASSWORD}, "email", "email is required."),
        ({"email": "  ", "password": PASSWORD}, "email", "email is required."),
        ({"email": "nope", "password": PASSWORD}, "email", "email must look like name@example.com."),
        ({"email": EMAIL}, "password", "password is required."),
        ({"email": EMAIL, "password": "short"}, "password", "password must be at least 8 characters."),
        ({"email": EMAIL, "password": "x" * 129}, "password", "password must be at most 128 characters."),
        ({"email": EMAIL, "password": " " * 8}, "password", "password can't be only spaces."),
        (
            {"email": EMAIL, "password": PASSWORD, "display_name": "x" * 121},
            "display_name",
            "display_name must be at most 120 characters.",
        ),
    ],
)
async def test_a_bad_registration_is_422_naming_the_field(client, body, field, message):
    resp = await client.post("/api/auth/register", json=body)

    assert resp.status_code == 422
    assert _error(resp) == {"code": "validation_error", "message": message, "field": field}


async def test_spaces_inside_a_password_are_kept(client):
    await _register(client, password="  spaced out  ")

    assert (await _login(client, password="  spaced out  ")).status_code == 200
    assert (await _login(client, password="spaced out")).status_code == 401


@pytest.mark.parametrize("data", [b"not json", b"[1, 2]"])
async def test_a_body_that_isnt_an_object_is_400(client, data):
    resp = await client.post(
        "/api/auth/register", content=data, headers={"Content-Type": "application/json"}
    )

    assert resp.status_code == 400
    assert _error(resp)["code"] == "bad_request"


async def test_logging_in_works_with_any_email_case(client):
    await _register(client)
    client.cookies.clear()

    resp = await _login(client, email=" MILES@bu.edu")

    assert resp.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 200


@pytest.mark.parametrize(
    ("email", "password"),
    [(EMAIL, "wrong password"), ("nobody@bu.edu", PASSWORD), (EMAIL, "x" * 129)],
)
async def test_a_failed_login_says_the_same_thing_every_time(client, email, password):
    await _register(client)
    client.cookies.clear()

    resp = await _login(client, email, password)

    assert resp.status_code == 401
    assert _error(resp)["message"] == "Invalid email or password."
    assert "set-cookie" not in resp.headers


async def test_me_is_401_when_signed_out(client):
    resp = await client.get("/api/auth/me")

    assert resp.status_code == 401
    assert _error(resp)["code"] == "unauthorized"


async def test_me_is_401_for_a_made_up_cookie(client):
    client.cookies.set("session", "made-up")

    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logging_out_ends_the_session_on_the_server(client, session):
    resp = await _register(client)
    token = resp.cookies["session"]

    assert (await client.post("/api/auth/logout")).status_code == 204

    assert await session.scalar(select(UserSession)) is None
    client.cookies.set("session", token)  # even if someone kept the old cookie
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logging_out_twice_is_fine(client):
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.post("/api/auth/logout")).status_code == 204


async def test_an_expired_session_doesnt_count(client, session):
    await _register(client)
    stored = await session.scalar(select(UserSession))
    stored.expires_at = utcnow() - timedelta(minutes=1)
    await session.commit()

    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logging_in_clears_that_users_expired_sessions(client, session):
    await _register(client)
    stored = await session.scalar(select(UserSession))
    stored.expires_at = utcnow() - timedelta(minutes=1)
    await session.commit()
    client.cookies.clear()

    await _login(client)

    assert len((await session.scalars(select(UserSession))).all()) == 1


async def test_an_unknown_url_uses_the_same_error_shape(client):
    resp = await client.get("/api/nothing-here")

    assert resp.status_code == 404
    assert _error(resp)["code"] == "not_found"


async def test_a_wrong_method_uses_the_same_error_shape(client):
    resp = await client.get("/api/auth/login")

    assert resp.status_code == 405
    assert _error(resp)["code"] == "method_not_allowed"
    assert "allow" in resp.headers
