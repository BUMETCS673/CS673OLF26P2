"""The `ai_generations` table: one row per batch of cards the AI suggested.

The suggestions wait here as `candidates` until the learner accepts or rejects each one
(decision A6 in code/plans/ITERATION_3_PLAN.md). Only accepting turns one into a `Card`.
The rows also count toward the daily cap, by `created_at`.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Data model development
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

from app.extensions import db
from app.models.base import iso, utcnow


class AiGeneration(db.Model):
    __tablename__ = "ai_generations"

    id = db.Column(db.Integer, primary_key=True)
    # On the row itself, so the daily cap is one count over this table with no join.
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # No relationship from Deck or User: the database's cascade removes a deck's
    # generations, just as it removes its cards.
    deck_id = db.Column(
        db.Integer, db.ForeignKey("decks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode = db.Column(db.String(16), nullable=False)             # "prompt" | "file" | "suggest"
    prompt = db.Column(db.String(2000), nullable=True)          # the prompt, or a file's focus note
    source_filename = db.Column(db.String(255), nullable=True)  # the file's name, never its contents
    requested_count = db.Column(db.Integer, nullable=False)
    model = db.Column(db.String(64), nullable=False)            # the provider's name: a Gemini model, or "fake"
    # [{"front", "back", "status"}], status "pending" | "accepted" | "rejected".
    # SQLAlchemy doesn't notice an in-place change to a JSON value, so build a new list
    # and assign it (rule 20).
    candidates = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self) -> dict:
        """The Generation shape in C3.

        Each candidate is numbered by its position, which never changes. `user_id`,
        `prompt` and `source_filename` stay on the server.
        """
        return {
            "id": self.id,
            "deck_id": self.deck_id,
            "mode": self.mode,
            "requested_count": self.requested_count,
            "model": self.model,
            "created_at": iso(self.created_at),
            "cards": [
                {
                    "index": index,
                    "front": candidate["front"],
                    "back": candidate["back"],
                    "status": candidate["status"],
                }
                for index, candidate in enumerate(self.candidates)
            ],
        }

    def __repr__(self) -> str:
        return f"<AiGeneration {self.id} deck={self.deck_id} mode={self.mode}>"
