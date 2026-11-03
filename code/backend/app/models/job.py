"""The `jobs` table: every piece of background work, and the outbox the relay publishes from."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"

# Kinds of job.
INDEX_MATERIAL = "index_material"
GENERATE_CARDS = "generate_cards"
EMBED_CARDS = "embed_cards"
REVIEW_PROBLEM_CARDS = "review_problem_cards"

JOBS_CHANNEL = "jobs_new"  # the Postgres channel that announces a new job to the relay


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    # Only unfinished jobs, so the relay's scan stays small however many jobs have ever run.
    __table_args__ = (
        Index(
            "ix_jobs_unfinished",
            "status",
            "enqueued_at",
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default=QUEUED)
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(255))
