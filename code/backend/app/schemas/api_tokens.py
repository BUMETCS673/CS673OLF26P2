"""Request and response bodies for personal access tokens."""

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.common import UtcDatetime, text_up_to

NAME_MAX = 120
TokenName = text_up_to(NAME_MAX)
DEFAULT_EXPIRY_DAYS = 90
MAX_EXPIRY_DAYS = 365


class ApiTokenCreate(BaseModel):
    name: TokenName
    expires_in_days: int | None = DEFAULT_EXPIRY_DAYS  # null makes a token that never expires

    @field_validator("expires_in_days", mode="before")
    @classmethod
    def _valid_expiry(cls, value: object) -> int | None:
        # type() rather than isinstance because True is an int to Python
        if value is not None and (type(value) is not int or not 1 <= value <= MAX_EXPIRY_DAYS):
            raise ValueError(
                f"expires_in_days must be a whole number from 1 to {MAX_EXPIRY_DAYS}, or null."
            )
        return value


class ApiTokenRead(BaseModel):
    """Never includes the token because only the create response shows it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: UtcDatetime
    last_used_at: UtcDatetime | None
    expires_at: UtcDatetime | None


class ApiTokenCreated(ApiTokenRead):
    token: str  # shown once because only its hash is stored
