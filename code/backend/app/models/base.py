"""Shared bits every model uses: UTC timestamps and how we put them in JSON."""

from datetime import datetime, timezone

from app.extensions import db


def utcnow() -> datetime:
    """Timezone-aware "now". Always UTC, so timestamps compare correctly."""
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    """Format a timestamp the way the API contract shows it: 2026-09-17T14:00:00Z.

    Values read back from Postgres come out naive, so assume UTC when there's no
    timezone attached rather than silently shifting the time.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class TimestampMixin:
    """`created_at` and `updated_at`, maintained for you."""

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
