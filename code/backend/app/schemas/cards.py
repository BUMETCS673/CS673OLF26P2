"""Request and response bodies for cards."""

from pydantic import BaseModel, ConfigDict

from app.schemas.common import UtcDatetime, text_up_to

TEXT_MAX = 2000
CardText = text_up_to(TEXT_MAX)


class CardCreate(BaseModel):
    """`origin` isn't accepted: only accepting an AI suggestion can set it."""

    front: CardText
    back: CardText


class CardUpdate(BaseModel):
    """Only the fields sent are changed, which is why the service uses `exclude_unset`."""

    # Not Optional, so an explicit null is rejected rather than saved.
    front: CardText = None
    back: CardText = None


class CardRead(BaseModel):
    """Only `state` and `due_at` of the schedule: the frontend never computes intervals."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    deck_id: int
    front: str
    back: str
    state: str
    due_at: UtcDatetime | None
    origin: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
