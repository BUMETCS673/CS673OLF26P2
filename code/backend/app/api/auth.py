"""Auth endpoints — WS1 (Miles).

    POST   /api/auth/register  {email, password, display_name?}  -> 201 User
    POST   /api/auth/login     {email, password}                 -> 200 User
    POST   /api/auth/logout                                      -> 204
    GET    /api/auth/me                                          -> 200 User | 401

Register and login both put a session cookie on the response; the browser sends it
back on every later request and `@login_required` reads it. `/me` is how the frontend
finds out on page load whether someone is still signed in.

Security notes, matching the plan's "Security basics":
  - passwords are hashed by `User.set_password`; the plain one is never stored or logged
  - emails are trimmed and lowercased, so Miles@BU.edu and miles@bu.edu are one account
  - a failed login says the same thing whether the email is unknown or the password is
    wrong, so nobody can use this endpoint to discover which emails have accounts
"""

import re

from flask import Blueprint, jsonify
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.errors import conflict, json_object, unauthorized, validation_error
from app.extensions import db
from app.models import User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

MAX_EMAIL_LENGTH = 255
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_DISPLAY_NAME_LENGTH = 120

# Deliberately not an RFC-complete email pattern -- those are famously wrong in both
# directions. This rules out the shapes that are obviously not addresses (`@`, `a@`,
# `a@b`) and leaves the real proof of validity to sending mail, which we don't do.
# Length is checked before this runs, so it never sees an unbounded string.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# One message for every kind of login failure. Two different messages would let someone
# work out which emails are registered by watching which error they get back.
INVALID_CREDENTIALS = "Invalid email or password."

# Checked against when no user matches, so a login attempt takes about as long whether
# or not the email exists. Without it, the response time itself answers the question.
_DUMMY_PASSWORD_HASH = generate_password_hash("not-a-real-password")


@auth_bp.post("/register")
def register():
    body = json_object()
    # Still needed even though the model normalizes on assignment: this value is also
    # used for the duplicate lookup below, and a query compares the string as given.
    email = User.normalize_email(_required_string(body, "email"))
    password = _required_string(body, "password", strip=False)
    display_name = _optional_string(body, "display_name", MAX_DISPLAY_NAME_LENGTH)

    _validate_email(email)
    _validate_password(password)

    if User.query.filter_by(email=email).first() is not None:
        raise conflict("That email is already registered.")

    user = User(email=email, display_name=display_name)
    user.set_password(password)
    db.session.add(user)

    try:
        db.session.commit()
    except IntegrityError:
        # Two registrations for the same email arriving at once: the unique constraint
        # catches the loser of the race, and it's still a 409 rather than a 500.
        db.session.rollback()
        # `from None`: losing the race is an expected outcome, not an internal error, so
        # the IntegrityError adds nothing to the traceback a reader would want.
        raise conflict("That email is already registered.") from None

    login_user(user)
    return jsonify(user.to_dict()), 201


@auth_bp.post("/login")
def login():
    body = json_object()
    # Not redundant with the model's validator -- that one only applies to what gets
    # written. This goes into a query, so without it MILES@BU.EDU finds nobody.
    email = User.normalize_email(_required_string(body, "email"))
    password = _required_string(body, "password", strip=False)

    if len(password) > MAX_PASSWORD_LENGTH:
        # No stored password can be longer than the cap, so this can't be anyone's --
        # same answer as any other failure, but without paying for the hash.
        raise unauthorized(INVALID_CREDENTIALS)

    user = User.query.filter_by(email=email).first()
    if user is None:
        check_password_hash(_DUMMY_PASSWORD_HASH, password)
        raise unauthorized(INVALID_CREDENTIALS)
    if not user.check_password(password):
        raise unauthorized(INVALID_CREDENTIALS)

    login_user(user)
    return jsonify(user.to_dict()), 200


@auth_bp.post("/logout")
def logout():
    """Always 204, even if nobody was signed in — logging out twice isn't an error."""
    logout_user()
    return "", 204


@auth_bp.get("/me")
@login_required
def me():
    """Who's signed in. 401 when nobody is, which is the answer the frontend wants."""
    return jsonify(current_user.to_dict()), 200


# --- reading and checking the request body -----------------------------------------
#
# The frontend checks these rules too, so the user gets a fast, friendly message. These
# checks are here because the frontend can be bypassed and is never the real defense.


def _required_string(body: dict, field: str, strip: bool = True) -> str:
    value = body.get(field)
    if value is None:
        raise validation_error(f"{field} is required.", field=field)
    if not isinstance(value, str):
        raise validation_error(f"{field} must be text.", field=field)
    if strip:
        value = value.strip()
    if not value:
        raise validation_error(f"{field} is required.", field=field)
    return value


def _optional_string(body: dict, field: str, max_length: int) -> str | None:
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise validation_error(f"{field} must be text.", field=field)
    value = value.strip()
    if not value:
        return None
    if len(value) > max_length:
        raise validation_error(
            f"{field} must be {max_length} characters or fewer.", field=field
        )
    return value


def _validate_email(email: str) -> None:
    # Length first, so the pattern below never runs against an unbounded string.
    if len(email) > MAX_EMAIL_LENGTH:
        raise validation_error(
            f"email must be {MAX_EMAIL_LENGTH} characters or fewer.", field="email"
        )
    if not EMAIL_PATTERN.match(email):
        raise validation_error("email must look like name@example.com.", field="email")


def _validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise validation_error(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters.",
            field="password",
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise validation_error(
            f"password must be {MAX_PASSWORD_LENGTH} characters or fewer.",
            field="password",
        )
    if not password.strip():
        # Spaces inside a password are fine and we never trim what gets stored --
        # trimming would quietly change someone's password. Only an entirely blank
        # one is rejected, which eight spaces otherwise passes as.
        raise validation_error("password can't be only spaces.", field="password")
