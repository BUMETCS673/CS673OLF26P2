"""Request and response bodies for a study session."""

from datetime import datetime, timedelta

from pydantic import BaseModel, field_validator

from app.models import Card
from app.scheduler import Rating, preview_intervals
from app.schemas.cards import CardRead


class ReviewRequest(BaseModel):
    rating: Rating

    @field_validator("rating", mode="before")
    @classmethod
    def _check_rating(cls, value: object) -> Rating:
        try:
            return Rating(value)
        except ValueError:
            raise ValueError(f"rating must be one of: {', '.join(Rating)}") from None


class StudyCardRead(CardRead):
    """A card, plus how many seconds until it's due for each rating."""

    intervals: dict[Rating, int]

    @classmethod
    def build(cls, card: Card, now: datetime) -> "StudyCardRead":
        previews = preview_intervals(card.schedule, now)
        return cls(
            **CardRead.model_validate(card).model_dump(),
            intervals={
                rating: delta // timedelta(seconds=1) for rating, delta in previews.items()
            },
        )


class DueCards(BaseModel):
    learning: list[StudyCardRead]
    review: list[StudyCardRead]
    new: list[StudyCardRead]
