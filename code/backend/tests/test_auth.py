"""WS1 — the four auth endpoints.

The six tests the plan asks for are the first six here; the rest cover the validation
rules and the "don't leak information" requirement from Security basics #5.
"""

import pytest

from app.models import User

GOOD = {"email": "miles@bu.edu", "password": "password123", "display_name": "Miles"}


@pytest.fixture
def register(client):
    def _register(**overrides):
        return client.post("/api/auth/register", json={**GOOD, **overrides})

    return _register


# --- the six the plan asks for ------------------------------------------------------


def test_register_creates_an_account(client, register):
    response = register()

    assert response.status_code == 201
    body = response.get_json()
    assert body["email"] == "miles@bu.edu"
    assert body["display_name"] == "Miles"
    assert body["id"] is not None
    assert User.query.count() == 1


def test_registering_a_taken_email_is_a_conflict_not_a_crash(register):
    register()

    response = register(display_name="Someone Else")

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "conflict"
    assert User.query.count() == 1


def test_login_with_the_wrong_password_is_rejected(client, register):
    register()

    response = client.post("/api/auth/login", json={"email": GOOD["email"], "password": "wrong"})

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


def test_me_is_401_when_signed_out(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


def test_me_returns_the_signed_in_user(client, register):
    register()
    client.post("/api/auth/login", json={"email": GOOD["email"], "password": GOOD["password"]})

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.get_json()["email"] == "miles@bu.edu"


def test_logout_then_me_is_401(client, register):
    register()

    logout = client.post("/api/auth/logout")
    response = client.get("/api/auth/me")

    assert logout.status_code == 204
    assert response.status_code == 401


# --- sessions -----------------------------------------------------------------------


def test_register_signs_you_in(client, register):
    register()

    assert client.get("/api/auth/me").status_code == 200


def test_login_signs_you_in(client, register):
    register()
    client.post("/api/auth/logout")

    response = client.post(
        "/api/auth/login", json={"email": GOOD["email"], "password": GOOD["password"]}
    )

    assert response.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_logout_while_signed_out_is_still_204(client):
    assert client.post("/api/auth/logout").status_code == 204


# --- security basics ----------------------------------------------------------------


def test_the_password_is_never_returned(client, register):
    body = register().get_json()

    assert not any("password" in key for key in body)


def test_the_password_is_hashed_not_stored(register):
    register()

    assert User.query.first().password_hash != GOOD["password"]


def test_an_unknown_email_and_a_wrong_password_look_identical(client, register):
    """Two different messages would let someone discover which emails have accounts."""
    register()

    unknown = client.post("/api/auth/login", json={"email": "nobody@bu.edu", "password": "whatever1"})
    wrong = client.post("/api/auth/login", json={"email": GOOD["email"], "password": "whatever1"})

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.get_json() == wrong.get_json()


def test_email_is_stored_lowercase_and_trimmed(client, register):
    register(email="  Miles@BU.edu  ")

    assert User.query.first().email == "miles@bu.edu"


def test_you_can_log_in_with_any_casing_of_your_email(client, register):
    register(email="miles@bu.edu")
    client.post("/api/auth/logout")

    response = client.post(
        "/api/auth/login", json={"email": "MILES@BU.EDU", "password": GOOD["password"]}
    )

    assert response.status_code == 200


# --- validation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"email": "not-an-email"}, "email"),
        ({"email": ""}, "email"),
        ({"email": "a@b.com", "password": "short"}, "password"),
        ({"password": ""}, "password"),
        ({"email": "a@" + "b" * 260 + ".com"}, "email"),
    ],
)
def test_register_rejects_bad_input(register, overrides, field):
    response = register(**overrides)

    assert response.status_code == 422
    body = response.get_json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["field"] == field


def test_register_requires_a_body(client):
    response = client.post("/api/auth/register", data="not json", content_type="application/json")

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "bad_request"


def test_a_password_of_exactly_eight_characters_is_allowed(register):
    assert register(password="12345678").status_code == 201


def test_display_name_is_optional(client):
    response = client.post(
        "/api/auth/register", json={"email": "a@b.com", "password": "password123"}
    )

    assert response.status_code == 201
    assert response.get_json()["display_name"] is None


def test_a_non_string_field_is_a_422_not_a_500(register):
    response = register(email=12345)

    assert response.status_code == 422
