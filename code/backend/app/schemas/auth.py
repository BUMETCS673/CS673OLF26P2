"""Request and response bodies for signing up and signing in."""

import re

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.user import normalize_email
from app.schemas.common import UtcDatetime

MAX_EMAIL_LENGTH = 255
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_DISPLAY_NAME_LENGTH = 120

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        email = normalize_email(value)
        if not email:
            raise ValueError("email is required.")
        # Length first, so the pattern never runs against an unbounded string.
        if len(email) > MAX_EMAIL_LENGTH:
            raise ValueError(f"email must be at most {MAX_EMAIL_LENGTH} characters.")
        if not _EMAIL_PATTERN.match(email):
            raise ValueError("email must look like name@example.com.")
        return email

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        # Never trimmed, because that would quietly change someone's password.
        if not value:
            raise ValueError("password is required.")
        if len(value) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters.")
        if len(value) > MAX_PASSWORD_LENGTH:
            raise ValueError(f"password must be at most {MAX_PASSWORD_LENGTH} characters.")
        if not value.strip():
            raise ValueError("password can't be only spaces.")
        return value

    @field_validator("display_name")
    @classmethod
    def _check_display_name(cls, value: str | None) -> str | None:
        name = (value or "").strip()
        if len(name) > MAX_DISPLAY_NAME_LENGTH:
            raise ValueError(f"display_name must be at most {MAX_DISPLAY_NAME_LENGTH} characters.")
        return name or None


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        email = normalize_email(value)
        if not email:
            raise ValueError("email is required.")
        return email

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        if not value:
            raise ValueError("password is required.")
        return value


class UserRead(BaseModel):
    """There is no password field, ever."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str | None
    created_at: UtcDatetime
