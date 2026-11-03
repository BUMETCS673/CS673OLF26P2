"""Requests and responses for problem card reviews."""

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.cards import CardRead
from app.schemas.common import UtcDatetime

REMOVE = "remove"  # a decision that deletes the card
BAD_DECISIONS = "decisions must list each recommended card once, with a valid option."


class ProblemCardReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deck_id: int
    status: str
    verification: str | None
    shared_cause: str | None
    recommendations: list[dict[str, Any]]
    decisions: list[dict[str, Any]] | None
    created_at: UtcDatetime
    completed_at: UtcDatetime | None


class DeckReview(BaseModel):
    review: ProblemCardReviewRead | None


class ReadyReview(BaseModel):
    review_id: int
    deck_id: int
    deck_name: str
    card_count: int


class ProblemCardSummary(BaseModel):
    processing: bool  # results may arrive soon
    ready: list[ReadyReview]


class Decisions(BaseModel):
    """`option` is an option's index, "remove", or null to keep the card as it is.

    The service checks these against the review. Each decision keeps only its two fields.
    """

    decisions: list[dict[str, Any]]

    @field_validator("decisions", mode="before")
    @classmethod
    def _valid_decisions(cls, value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise ValueError(BAD_DECISIONS)
        cleaned = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError(BAD_DECISIONS)
            card_id, option = item.get("card_id"), item.get("option")
            # `type() is int`, not isinstance: True is an int to Python.
            if type(card_id) is not int:
                raise ValueError(BAD_DECISIONS)
            if option is not None and option != REMOVE and type(option) is not int:
                raise ValueError(BAD_DECISIONS)
            cleaned.append({"card_id": card_id, "option": option})
        return cleaned


class DecisionsApplied(BaseModel):
    review: ProblemCardReviewRead
    cards: list[CardRead]
