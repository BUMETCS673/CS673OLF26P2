"""The `cards` table."""

from app.extensions import db
from app.models.base import TimestampMixin, iso


class Card(TimestampMixin, db.Model):
    __tablename__ = "cards"

    id = db.Column(db.Integer, primary_key=True)
    deck_id = db.Column(
        db.Integer,
        db.ForeignKey("decks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    front = db.Column(db.String(2000), nullable=False)  # the question
    back = db.Column(db.String(2000), nullable=False)   # the answer

    deck = db.relationship("Deck", back_populates="cards")

    def to_dict(self) -> dict:
        """The `Card` shape from the API contract."""
        return {
            "id": self.id,
            "deck_id": self.deck_id,
            "front": self.front,
            "back": self.back,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }

    def __repr__(self) -> str:
        return f"<Card {self.id} deck={self.deck_id}>"
