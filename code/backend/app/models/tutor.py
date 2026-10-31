"""The deck tutor's table. Messages live in the LangGraph checkpointer, under `thread_id`."""

from app.extensions import db
from app.models.base import utcnow

IDLE = "idle"
REPLYING = "replying"                    # a request holds the conversation
AWAITING_DECISION = "awaiting_decision"  # paused at the graph's interrupt


class TutorConversation(db.Model):
    """One per deck."""

    __tablename__ = "tutor_conversations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    deck_id = db.Column(
        db.Integer, db.ForeignKey("decks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    thread_id = db.Column(db.String(36), nullable=False, unique=True)
    status = db.Column(db.String(24), nullable=False, default=IDLE)
    status_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    # {"id", "cards", "verification"}. The server adds these cards, never ones from the browser.
    pending_proposal = db.Column(db.JSON, nullable=True)
    message_count = db.Column(db.Integer, nullable=False, default=0)
