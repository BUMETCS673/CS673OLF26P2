"""Reading a background job, and following it live."""

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi.sse import ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.jobs.events import READ_FAILURES, JobEvents
from app.models import Job, User
from app.repositories.jobs import JobRepository
from app.schemas.jobs import JobEvent, JobRead

logger = logging.getLogger(__name__)

JOB_NOT_FOUND = "Job not found"
STATUS_EVENT = "status"
WAIT_SECONDS = 15.0  # how long to wait on Redis before checking the job's row again


class JobService:
    def __init__(self, session: AsyncSession, jobs: JobRepository, events: JobEvents):
        self.session = session
        self.jobs = jobs
        self.events = events

    async def _owned(self, job_id: int, user_id: int) -> Job:
        job = await self.jobs.get_owned(job_id, user_id)
        if job is None:
            raise NotFound(JOB_NOT_FOUND)
        return job

    async def get(self, job_id: int, user: User) -> JobRead:
        return JobRead.model_validate(await self._owned(job_id, user.id))

    async def _latest(self, job_id: int, user_id: int) -> JobEvent:
        """Read the row, then return the connection, since a stream can stay open for minutes."""
        job = await self._owned(job_id, user_id)
        event = JobEvent(status=job.status, result=job.result, error=job.error)
        await self.session.close()
        return event

    async def follow(self, job_id: int, user_id: int, after: str) -> AsyncIterator[ServerSentEvent]:
        """The job's status now, then each change, ending when it finishes.

        Replaying an event a client already saw is harmless, since each one is a full status. Only
        Redis events carry an id, so `after` always stays a valid stream position.
        """
        latest = await self._latest(job_id, user_id)
        yield ServerSentEvent(data=latest, event=STATUS_EVENT)
        if latest.finished:
            return

        while True:
            try:
                entries = await self.events.read(job_id, after, int(WAIT_SECONDS * 1000))
            except READ_FAILURES as error:
                logger.warning("job follow outcome=redis_failed type=%s", type(error).__name__)
                await asyncio.sleep(WAIT_SECONDS)
                entries = []

            for event_id, event in entries:
                after = event_id
                yield ServerSentEvent(data=event, event=STATUS_EVENT, id=event_id)
                if event.finished:
                    return

            if not entries:
                # Redis may have lost the event, or be down, but the row is always right.
                latest = await self._latest(job_id, user_id)
                if latest.finished:
                    yield ServerSentEvent(data=latest, event=STATUS_EVENT)
                    return
