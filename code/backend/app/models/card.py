"""The `cards` table."""

from app.extensions import db
from app.models.base import TimestampMixin, as_utc, iso
from app.scheduler import STARTING_EASE, CardSchedule, CardState


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

    # Scheduling: the same fields Anki keeps on a card. `default` covers rows created in
    # Python; `server_default` is what migration 0002 filled the existing rows with.
    # Read and write them together through `schedule` below.
    state = db.Column(
        db.String(16), nullable=False, default=CardState.NEW.value, server_default=CardState.NEW.value
    )
    due_at = db.Column(db.DateTime(timezone=True), nullable=True)  # null only while new
    interval_days = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    ease_factor = db.Column(  # thousandths: 2500 = 250%
        db.Integer, nullable=False, default=STARTING_EASE, server_default=str(STARTING_EASE)
    )
    step = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    lapses = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    deck = db.relationship("Deck", back_populates="cards")

    @property
    def schedule(self) -> CardSchedule:
        """This card's scheduling fields, in the shape `app.scheduler` works with."""
        return CardSchedule(
            state=CardState(self.state),
            # SQLite returns timestamps without a timezone; the scheduler needs them aware.
            due_at=as_utc(self.due_at),
            interval_days=self.interval_days,
            ease_factor=self.ease_factor,
            step=self.step,
            lapses=self.lapses,
        )

    @schedule.setter
    def schedule(self, value: CardSchedule) -> None:
        # CardState() refuses anything that isn't one of the four states -- before any
        # field has been touched, so a bad schedule changes nothing.
        self.state = CardState(value.state).value
        self.due_at = value.due_at
        self.interval_days = value.interval_days
        self.ease_factor = value.ease_factor
        self.step = value.step
        self.lapses = value.lapses

    def to_dict(self) -> dict:
        """The `Card` shape from the API contract.

        Only `state` and `due_at` of the scheduling fields: the frontend has no use for
        the rest, and must never compute intervals itself (rule 6 in the Lab 3 plan).
        """
        return {
            "id": self.id,
            "deck_id": self.deck_id,
            "front": self.front,
            "back": self.back,
            "state": self.state,
            "due_at": iso(self.due_at),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }

    def __repr__(self) -> str:
        return f"<Card {self.id} deck={self.deck_id}>"
