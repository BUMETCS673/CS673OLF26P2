"""The `cards` table."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import EMBEDDING_DIMENSIONS
from app.models.base import Base, TimestampMixin
from app.scheduler import STARTING_EASE, CardSchedule, CardState


class Card(TimestampMixin, Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    front: Mapped[str] = mapped_column(String(2000))
    back: Mapped[str] = mapped_column(String(2000))

    # Scheduling. Read and write these together through `schedule`.
    state: Mapped[str] = mapped_column(String(16), default=CardState.NEW.value)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # null while new
    interval_days: Mapped[int] = mapped_column(default=0)
    ease_factor: Mapped[int] = mapped_column(default=STARTING_EASE)  # thousandths: 2500 = 250%
    step: Mapped[int] = mapped_column(default=0)
    lapses: Mapped[int] = mapped_column(default=0)
    # Set only by a learner's answer, unlike `updated_at`, which edits also change.
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    origin: Mapped[str] = mapped_column(String(16), default="manual")  # "manual" | "ai"
    generation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_generations.id", ondelete="SET NULL")
    )
    # The card counts as a problem card when `lapses` reaches this. Handling it raises the level.
    problem_at_lapses: Mapped[int] = mapped_column(default=4)

    # For searching within this deck. Separate from the knowledge base, which every user searches,
    # so a manual card stays private. Deferred, so reading cards doesn't load every vector.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), deferred=True
    )
    embedding_model: Mapped[str | None] = mapped_column(String(64))

    @property
    def schedule(self) -> CardSchedule:
        """This card's scheduling fields, in the shape `app.scheduler` works with."""
        return CardSchedule(
            state=CardState(self.state),
            due_at=self.due_at,
            interval_days=self.interval_days,
            ease_factor=self.ease_factor,
            step=self.step,
            lapses=self.lapses,
        )

    @schedule.setter
    def schedule(self, value: CardSchedule) -> None:
        # CardState() refuses a bad state before any field changes.
        self.state = CardState(value.state).value
        self.due_at = value.due_at
        self.interval_days = value.interval_days
        self.ease_factor = value.ease_factor
        self.step = value.step
        self.lapses = value.lapses
