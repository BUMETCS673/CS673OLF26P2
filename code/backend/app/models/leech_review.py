"""The `leech_reviews` table: one row per Leech Doctor run. It doubles as the job queue."""

from app.extensions import db
from app.models.base import iso, utcnow

QUEUED = "queued"        # waiting for a background job
RUNNING = "running"      # a job holds it
PENDING = "pending"      # waiting at the graph's interrupt for the learner's decisions
COMPLETED = "completed"
FAILED = "failed"        # the AI call failed on both attempts
ACTIVE = (QUEUED, RUNNING, PENDING)  # a deck has at most one review in these statuses


class LeechReview(db.Model):
    __tablename__ = "leech_reviews"

    id = db.Column(db.Integer, primary_key=True)
    # Identifies the paused run in the LangGraph checkpointer. Set when a job claims the row.
    thread_id = db.Column(db.String(36), nullable=True, unique=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    deck_id = db.Column(
        db.Integer, db.ForeignKey("decks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = db.Column(db.String(16), nullable=False, default=QUEUED)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)  # finds lost jobs
    card_ids = db.Column(db.JSON, nullable=True)  # the cards the latest attempt covered
    model = db.Column(db.String(64), nullable=True)
    model_calls = db.Column(db.Integer, nullable=False, default=0)  # counted by the caps
    input_tokens = db.Column(db.Integer, nullable=False, default=0)
    output_tokens = db.Column(db.Integer, nullable=False, default=0)
    judge_model = db.Column(db.String(64), nullable=True)
    judge_input_tokens = db.Column(db.Integer, nullable=False, default=0)
    judge_output_tokens = db.Column(db.Integer, nullable=False, default=0)
    verification = db.Column(db.String(16), nullable=True)  # "passed" | "skipped"
    shared_cause = db.Column(db.Text, nullable=True)
    # [{"card_id", "front", "back", "lapses", "options": [{"kind", "reason", "cards"}]}]
    # `lapses` keeps the count from before the fix, for measuring whether it worked.
    recommendations = db.Column(db.JSON, nullable=False, default=list)
    # [{"card_id", "kind", "new_card_ids"}]. `kind` is null when the card was kept.
    decisions = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "deck_id": self.deck_id,
            "status": self.status,
            "shared_cause": self.shared_cause,
            "verification": self.verification,
            "recommendations": self.recommendations,
            "decisions": self.decisions,
            "created_at": iso(self.created_at),
            "completed_at": iso(self.completed_at),
        }
