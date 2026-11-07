"""The `api_tokens` table: personal access tokens that let an MCP client act as a user."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))  # the user's label such as "Claude Code"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # the token is never stored
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # None never ends
    # set instead of deleting the row to keep a record of when the token stopped working
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
