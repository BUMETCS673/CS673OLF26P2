"""The `oauth_clients` table: apps like Claude or ChatGPT that registered to connect over OAuth."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class OAuthClient(Base):
    __tablename__ = "oauth_clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True)  # a UUID the SDK assigns
    # The SDK's whole registration record. Its client secret stays readable because the SDK
    # compares it as given. A secret alone can't get a token without the user's consent.
    client_info: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # when it first got tokens which lets cleanup tell an idle client from one never used
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
