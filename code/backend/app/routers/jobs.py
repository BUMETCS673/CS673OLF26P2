"""Background jobs. Someone else's job answers 404, never 403."""

from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.dependencies import CurrentUser, JobServiceDep, OwnedJob
from app.jobs.events import START
from app.schemas.jobs import JobRead

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job(job: OwnedJob) -> JobRead:
    return job


@router.get("/{job_id}/events", response_class=EventSourceResponse)
async def follow_job(
    job: OwnedJob,
    user: CurrentUser,
    service: JobServiceDep,
    # Browsers send this by themselves when they reconnect.
    last_event_id: Annotated[
        str | None, Header(alias="Last-Event-ID", pattern=r"^\d+-\d+$")
    ] = None,
) -> AsyncIterable[ServerSentEvent]:
    """The ownership check is `OwnedJob`, a dependency, so it can still answer 404 here."""
    async for event in service.follow(job.id, user.id, last_event_id or START):
        yield event
