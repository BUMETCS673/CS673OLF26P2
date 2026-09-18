"""The `decks` table."""

from app.extensions import db
from app.models.base import TimestampMixin, iso


class Deck(TimestampMixin, db.Model):
    __tablename__ = "decks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(1000), nullable=True)

    user = db.relationship("User", back_populates="decks")

    # Deleting a deck deletes its cards. The database enforces it (ON DELETE CASCADE)
    # and passive_deletes lets it, instead of SQLAlchemy loading every card to delete
    # them one at a time.
    cards = db.relationship(
        "Card",
        back_populates="deck",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Card.id",
    )

    @property
    def card_count(self) -> int:
        return len(self.cards)

    def to_dict(self) -> dict:
        """The `Deck` shape from the API contract."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "card_count": self.card_count,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }

    def __repr__(self) -> str:
        return f"<Deck {self.id} {self.name!r}>"
