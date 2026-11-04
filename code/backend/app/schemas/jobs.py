"""Background jobs, as the API shows them."""

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.job import DONE, FAILED
from app.schemas.common import UtcDatetime


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    status: str
    result: dict[str, Any] | None
    error: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class JobEvent(BaseModel):
    """A job's status at one moment, sent to whoever is following it."""

    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    progress: dict[str, Any] | None = None  # how far a running job has got, in its own terms

    @property
    def finished(self) -> bool:
        return self.status in (DONE, FAILED)
