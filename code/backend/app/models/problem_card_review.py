"""The `problem_card_reviews` table: one row per run of the problem cards graph."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow

QUEUED = "queued"  # its job hasn't finished, which the job's own row tracks in detail
PENDING = "pending"  # paused at the graph's interrupt for the learner's decisions
COMPLETED = "completed"
FAILED = "failed"  # its job ran out of attempts


class ProblemCardReview(Base):
    __tablename__ = "problem_card_reviews"
    # A deck has at most one active review, which holds even if two requests race.
    __table_args__ = (
        Index(
            "uq_problem_card_reviews_one_active",
            "deck_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'pending')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Identifies the paused run in the LangGraph checkpointer.
    thread_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default=QUEUED)
    card_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    verification: Mapped[str | None] = mapped_column(String(16))  # "passed" | "skipped"
    shared_cause: Mapped[str | None] = mapped_column(Text)
    # [{"card_id", "front", "back", "lapses", "options": [{"kind", "reason", "cards"}]}]
    recommendations: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    # [{"card_id", "kind", "new_card_ids"}]. `kind` is null when the card was kept.
    decisions: Mapped[list[dict] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
