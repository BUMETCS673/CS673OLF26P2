"""A learner saying one of their cards is wrong, which hides what it came from."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class CardReport(Base):
    __tablename__ = "card_reports"
    __table_args__ = (UniqueConstraint("user_id", "card_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChunkReport(Base):
    """One shared chunk a report hid, held against the learner who uploaded or first accepted it."""

    __tablename__ = "chunk_reports"
    __table_args__ = (UniqueConstraint("reporter_id", "chunk_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    target_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_chunks.langchain_id", ondelete="CASCADE")
    )
    # Stored, so counting a target's reporters never has to work out each reporter's trust.
    reporter_trusted: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
