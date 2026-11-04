"""Types shared by the API's schemas."""

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, StringConstraints


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# Serialized the way the API contract shows it: 2026-09-17T14:00:00Z.
UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


def text_up_to(max_length: int) -> Any:
    """A stripped, non-blank string within `max_length`."""
    return Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)
    ]


def required_text(value: object, field: str, max_length: int) -> str:
    """A stripped, non-blank string within `max_length`, for a `before` validator."""
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise ValueError(f"{field} is required.")
    if len(text) > max_length:
        raise ValueError(f"{field} must be at most {max_length} characters.")
    return text
