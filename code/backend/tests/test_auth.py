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

    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@bu.edu", "password": "whatever1"}
    )
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
        # shapes that aren't addresses -- "contains @" used to be the whole check
        ({"email": "@"}, "email"),
        ({"email": "a@"}, "email"),
        ({"email": "@b.com"}, "email"),
        ({"email": "a@b"}, "email"),
        ({"email": "a b@c.com"}, "email"),
        # eight spaces used to pass the length check and become a real password
        ({"password": "        "}, "password"),
        ({"password": "p" * 129}, "password"),
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


def test_register_without_a_json_content_type_is_a_400(client):
    """A curl without -H 'Content-Type: application/json' is the common way to hit this.

    Flask answers a bare get_json() with a 415, whose code isn't in the contract;
    these endpoints read bodies with json_object(), so it stays a 400.
    """
    response = client.post(
        "/api/auth/register", data='{"email": "a@b.com", "password": "password123"}'
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "bad_request"


def test_a_password_keeps_its_spaces(register, client):
    """Only an all-blank password is rejected; we never trim what gets stored.

    Trimming would quietly change someone's password, so " hunter2 " stays as typed
    and is the only thing that logs you in.
    """
    assert register(email="spaces@bu.edu", password=" hunter2 ").status_code == 201
    client.post("/api/auth/logout")

    assert client.post(
        "/api/auth/login", json={"email": "spaces@bu.edu", "password": "hunter2"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"email": "spaces@bu.edu", "password": " hunter2 "}
    ).status_code == 200


def test_a_password_at_the_length_limit_is_allowed(register):
    assert register(password="p" * 128).status_code == 201


@pytest.mark.parametrize(
    "body, status, code",
    [
        ({"email": GOOD["email"]}, 422, "validation_error"),              # no password
        ({"password": GOOD["password"]}, 422, "validation_error"),        # no email
        ({"email": 123, "password": GOOD["password"]}, 422, "validation_error"),
        ({"email": GOOD["email"], "password": 123}, 422, "validation_error"),
        ({"email": "", "password": GOOD["password"]}, 422, "validation_error"),
    ],
)
def test_login_rejects_bad_input(client, register, body, status, code):
    """Login had no bad-input coverage at all -- every test sent a well-formed body."""
    register()
    client.post("/api/auth/logout")

    response = client.post("/api/auth/login", json=body)

    assert response.status_code == status
    assert response.get_json()["error"]["code"] == code


def test_login_requires_a_body(client):
    assert client.post(
        "/api/auth/login", data="not json", content_type="application/json"
    ).status_code == 400


def test_login_without_a_json_content_type_is_a_400(client):
    response = client.post(
        "/api/auth/login", data='{"email": "a@b.com", "password": "password123"}'
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "bad_request"


def test_an_over_long_password_at_login_is_the_normal_401(client, register):
    """Rejected without hashing, but it must look like any other failed login.

    A different status here would tell an attacker their guess was merely too long
    rather than wrong, and 422 would split the uniform failure message.
    """
    register()
    client.post("/api/auth/logout")

    response = client.post(
        "/api/auth/login", json={"email": GOOD["email"], "password": "p" * 5000}
    )

    assert response.status_code == 401
    assert response.get_json()["error"]["message"] == "Invalid email or password."


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
