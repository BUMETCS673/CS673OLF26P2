"""Request and response bodies for cards."""

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.common import UtcDatetime, required_text

TEXT_MAX = 2000


class CardCreate(BaseModel):
    """`origin` isn't accepted: only accepting an AI suggestion can set it."""

    front: str
    back: str

    @field_validator("front", "back", mode="before")
    @classmethod
    def _check_text(cls, value: object, info) -> str:
        return required_text(value, info.field_name, TEXT_MAX)


class CardUpdate(BaseModel):
    """Only the fields sent are changed, which is why the service uses `exclude_unset`."""

    front: str | None = None
    back: str | None = None

    @field_validator("front", "back", mode="before")
    @classmethod
    def _check_text(cls, value: object, info) -> str:
        return required_text(value, info.field_name, TEXT_MAX)


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
