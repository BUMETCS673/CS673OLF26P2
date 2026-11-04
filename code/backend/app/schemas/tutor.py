"""Requests and responses for the deck tutor."""

from typing import Any

from pydantic import BaseModel, StrictBool

from app.schemas.common import text_up_to

MESSAGE_MAX = 2000
MessageText = text_up_to(MESSAGE_MAX)


class TutorMessageCreate(BaseModel):
    text: MessageText


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
