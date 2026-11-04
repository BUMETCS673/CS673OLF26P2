"""The `ai_usage` table: one row per model per run, which every budget reads from."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class AiUsage(Base):
    __tablename__ = "ai_usage"
    # One per kind of budget check, each covering what it sums, so the checks never read the table.
    __table_args__ = (
        Index(
            "ix_ai_usage_model_created_at", "model", "created_at", postgresql_include=["calls"]
        ),
        Index(
            "ix_ai_usage_feature_created_at",
            "feature",
            "created_at",
            postgresql_include=["calls", "user_id"],
        ),
        # Leads with `user_id`, so it also serves the cascade when a user is deleted.
        Index(
            "ix_ai_usage_user_id_feature_created_at",
            "user_id",
            "feature",
            "created_at",
            postgresql_include=["calls"],
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    feature: Mapped[str] = mapped_column(String(16))
    role: Mapped[str] = mapped_column(String(16))  # "writer" | "judge" | "helper" | "embedder"
    model: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Survives its deck, so deleting a deck doesn't refund quota.
    deck_id: Mapped[int | None] = mapped_column(ForeignKey("decks.id", ondelete="SET NULL"))
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    calls: Mapped[int]
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
