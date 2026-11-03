"""The `ai_generations` table: one row per batch of suggested cards, waiting for review."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class AiGeneration(Base):
    __tablename__ = "ai_generations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Unique, so a job retried after saving can't create a second batch.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), unique=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(16))  # "prompt" | "file"
    prompt: Mapped[str | None] = mapped_column(String(2000))  # the prompt, or a file's topic
    source_filename: Mapped[str | None] = mapped_column(String(255))
    requested_count: Mapped[int]
    model: Mapped[str] = mapped_column(String(64))
    verification: Mapped[str | None] = mapped_column(String(16))  # "passed" | "skipped"
    empty: Mapped[bool] = mapped_column(default=False)  # no cards survived, so it isn't counted
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    # [{"front", "back", "status"}], status "pending" | "accepted" | "rejected".
    # SQLAlchemy doesn't notice an in-place change, so build a new list and assign it.
    candidates: Mapped[list[dict]] = mapped_column(JSONB)
    # The knowledge chunks the run read. A batch shares them, since the writer doesn't say which
    # card used which one.
    source_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
