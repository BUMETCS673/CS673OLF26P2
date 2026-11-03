"""The `ai_usage` table: one row per model per run, for every AI feature.

Every budget reads from here. A row outlives its deck, so deleting a deck doesn't refund quota.
"""

from app.extensions import db
from app.models.base import utcnow


class AiUsage(db.Model):
    __tablename__ = "ai_usage"

    id = db.Column(db.Integer, primary_key=True)
    feature = db.Column(db.String(16), nullable=False)  # "generate" | "leech" | "tutor"
    role = db.Column(db.String(16), nullable=False)     # "writer" | "judge"
    model = db.Column(db.String(64), nullable=False)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    deck_id = db.Column(db.Integer, db.ForeignKey("decks.id", ondelete="SET NULL"), nullable=True)
    prompt_version = db.Column(db.String(16), nullable=True)
    calls = db.Column(db.Integer, nullable=False)
    input_tokens = db.Column(db.Integer, nullable=False)
    output_tokens = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
