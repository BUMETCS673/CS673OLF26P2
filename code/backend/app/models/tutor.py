"""The deck tutor's table. Messages live in the LangGraph checkpointer, under `thread_id`."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow

IDLE = "idle"
REPLYING = "replying"                    # a request holds the conversation
AWAITING_DECISION = "awaiting_decision"  # paused at the graph's interrupt


class TutorConversation(Base):
    """One per deck."""

    __tablename__ = "tutor_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), unique=True)
    thread_id: Mapped[str] = mapped_column(String(36), unique=True)
    status: Mapped[str] = mapped_column(String(24), default=IDLE)
    status_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # {"id", "cards", "verification"}. The server adds these cards, never ones from the browser.
    pending_proposal: Mapped[dict | None] = mapped_column(JSONB)
    message_count: Mapped[int] = mapped_column(default=0)
