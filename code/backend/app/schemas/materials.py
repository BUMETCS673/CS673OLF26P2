"""Uploaded study files, as the API shows them."""

from pydantic import BaseModel, ConfigDict

from app.schemas.common import UtcDatetime


class MaterialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    status: str
    stage: str
    chunks_total: int
    chunks_done: int
    suggested_topics: list[str] | None
    error: str | None
    job_id: int | None  # follow this job for live progress
    created_at: UtcDatetime
    updated_at: UtcDatetime
