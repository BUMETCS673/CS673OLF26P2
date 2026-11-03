"""Requests and responses for the deck tutor."""

from typing import Any

from pydantic import BaseModel, StrictBool, field_validator

from app.schemas.common import required_text

MESSAGE_MAX = 2000


class TutorMessageCreate(BaseModel):
    text: str

    @field_validator("text", mode="before")
    @classmethod
    def _check_text(cls, value: object, info) -> str:
        return required_text(value, info.field_name, MESSAGE_MAX)


class ProposalDecision(BaseModel):
    proposal_id: str
    accept: StrictBool


class TutorMessage(BaseModel):
    role: str
    text: str
    error: bool = False


class TutorView(BaseModel):
    enabled: bool
    status: str
    messages: list[TutorMessage]
    proposal: dict[str, Any] | None  # {"id", "cards", "verification"}
