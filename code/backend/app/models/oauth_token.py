"""The `oauth_tokens` table: one row per access and refresh token pair given to an OAuth client."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), index=True
    )
    # only keyed hashes like sessions and personal access tokens
    access_hash: Mapped[str] = mapped_column(String(64), unique=True)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scope: Mapped[str] = mapped_column(String(1000), default="")  # space-separated as in OAuth
    resource: Mapped[str | None] = mapped_column(String(500))  # the RFC 8707 resource asked for
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # set on revoke and on refresh because each refresh replaces the whole pair
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
