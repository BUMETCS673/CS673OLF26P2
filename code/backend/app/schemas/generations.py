"""Requests and responses for generating cards."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.schemas.cards import CardRead
from app.schemas.common import UtcDatetime, required_text

PROMPT = "prompt"
FILE = "file"
MAX_CARDS = 25
PROMPT_MAX = 2000
TOPIC_MAX = 500


class GenerateRequest(BaseModel):
    """What's required depends on `mode`, so each field checks it, reporting its own name."""

    mode: str
    count: int
    prompt: str | None = Field(default=None, validate_default=True)
    document_id: int | None = Field(default=None, validate_default=True)
    topic: str | None = Field(default=None, validate_default=True)

    @field_validator("mode", mode="before")
    @classmethod
    def _valid_mode(cls, value: object) -> str:
        if value not in (PROMPT, FILE):
            raise ValueError(f"mode must be one of: {PROMPT}, {FILE}.")
        return value

    @field_validator("count", mode="before")
    @classmethod
    def _valid_count(cls, value: object) -> int:
        # `type() is int`, not isinstance: True is an int to Python.
        if type(value) is not int or not 1 <= value <= MAX_CARDS:
            raise ValueError(f"count must be a whole number from 1 to {MAX_CARDS}.")
        return value

    @field_validator("prompt", mode="before")
    @classmethod
    def _valid_prompt(cls, value: object, info: ValidationInfo) -> str | None:
        if info.data.get("mode") != PROMPT:
            return None
        return required_text(value, "prompt", PROMPT_MAX)

    @field_validator("document_id", mode="before")
    @classmethod
    def _valid_document_id(cls, value: object, info: ValidationInfo) -> int | None:
        if info.data.get("mode") != FILE:
            return None
        if type(value) is not int:
            raise ValueError("document_id must be a whole number.")
        return value

    @field_validator("topic", mode="before")
    @classmethod
    def _valid_topic(cls, value: object, info: ValidationInfo) -> str | None:
        if info.data.get("mode") != FILE:
            return None
        return required_text(value, "topic", TOPIC_MAX)


class JobStarted(BaseModel):
    job_id: int


BAD_INDEXES = "indexes must be a non-empty list of card positions."


class Decision(BaseModel):
    """Which of a batch's cards to accept or reject. The service checks they're in range."""

    indexes: list[int]

    @field_validator("indexes", mode="before")
    @classmethod
    def _valid_indexes(cls, value: object) -> list[int]:
        # `type() is int`, not isinstance: True is an int to Python.
        if not isinstance(value, list) or not value or any(type(i) is not int for i in value):
            raise ValueError(BAD_INDEXES)
        return value


class Suggestions(BaseModel):
    topics: list[str]


class GenerationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deck_id: int
    mode: str
    prompt: str | None
    source_filename: str | None
    requested_count: int
    model: str
    verification: str | None
    empty: bool
    candidates: list[dict[str, Any]]
    created_at: UtcDatetime


class Accepted(BaseModel):
    cards: list[CardRead]
    generation: GenerationRead
