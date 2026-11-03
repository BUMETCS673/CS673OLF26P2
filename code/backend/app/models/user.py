"""The `users` table."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.models.base import Base, utcnow


def normalize_email(email: str) -> str:
    """Trim and lowercase, so Miles@BU.edu and miles@bu.edu are one account."""
    return email.strip().lower()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Stored, not worked out on each read: only finishing a deck or reports change it.
    trusted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when reports take trust away. Only study after this earns it back.
    trust_lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @validates("email")
    def _normalize_email(self, _key: str, value: str) -> str:
        """Keeps the unique constraint meaning one account. Lookups must normalize too."""
        return normalize_email(value)
