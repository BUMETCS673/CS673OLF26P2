"""Request and response bodies for decks."""

from pydantic import BaseModel, field_validator

from app.models import Deck
from app.schemas.common import UtcDatetime, text_up_to

NAME_MAX = 120
DeckName = text_up_to(NAME_MAX)
DESCRIPTION_MAX = 1000


def _clean_description(value: object) -> str | None:
    # Optional, kept as sent, and cleared with null.
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("description must be text.")
    if len(value) > DESCRIPTION_MAX:
        raise ValueError(f"description must be at most {DESCRIPTION_MAX} characters.")
    return value


class DeckCreate(BaseModel):
    name: DeckName
    description: str | None = None

    @field_validator("description", mode="before")
    @classmethod
    def _check_description(cls, value: object) -> str | None:
        return _clean_description(value)


class DeckUpdate(BaseModel):
    """Only the fields sent are changed, which is why the service uses `exclude_unset`."""

    # Not Optional, so an explicit null is rejected rather than saved.
    name: DeckName = None
    description: str | None = None

    @field_validator("description", mode="before")
    @classmethod
    def _check_description(cls, value: object) -> str | None:
        return _clean_description(value)


class DueCounts(BaseModel):
    """How many cards GET /api/decks/{id}/due would serve right now."""

    learning: int = 0
    review: int = 0
    new: int = 0


class DeckRead(BaseModel):
    id: int
    name: str
    description: str | None
    card_count: int
    due_counts: DueCounts
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @classmethod
    def build(cls, deck: Deck, card_count: int, due_counts: DueCounts) -> "DeckRead":
        return cls(
            id=deck.id,
            name=deck.name,
            description=deck.description,
            card_count=card_count,
            due_counts=due_counts,
            created_at=deck.created_at,
            updated_at=deck.updated_at,
        )
