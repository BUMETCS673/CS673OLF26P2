"""Reading a background job, and following it live."""

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi.sse import ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import found
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
        self.session = session  # one request's transaction so nothing saves until commit
        self.jobs = jobs
        self.events = events  # the Redis stream the worker publishes each status to

    async def _owned(self, job_id: int, user_id: int) -> Job:
        return found(await self.jobs.get_owned(job_id, user_id), JOB_NOT_FOUND)

    async def get(self, job_id: int, user: User) -> JobRead:
        return JobRead.model_validate(await self._owned(job_id, user.id))  # one poll from the row

    async def _latest(self, job_id: int, user_id: int) -> JobEvent:
        """Read the row, then return the connection, since a stream can stay open for minutes."""
        job = await self._owned(job_id, user_id)  # also re-checks ownership on every read
        event = JobEvent(status=job.status, result=job.result, error=job.error)
        await self.session.close()  # back to the pool so open streams don't hold connections
        return event

    async def follow(self, job_id: int, user_id: int, after: str) -> AsyncIterator[ServerSentEvent]:
        """The job's status now, then each change, ending when it finishes.

        Replaying an event a client already saw is harmless, since each one is a full status. Only
        Redis events carry an id, so `after` always stays a valid stream position.
        """
        # Step 1: send the job's status from its row and stop if it's already finished
        # the row stays right even if Redis lost events
        latest = await self._latest(job_id, user_id)
        logger.info("job follow started", extra={"job_id": job_id, "status": latest.status})
        # no id since it's not a stream position
        yield ServerSentEvent(data=latest, event=STATUS_EVENT)
        if latest.finished:  # already done or failed so one event and the stream closes
            return

        while True:
            # Step 2: wait on Redis for the job's next events and keep going if Redis fails
            try:
                # XREAD BLOCK waits in one call with no polling returning as soon as an event lands
                entries = await self.events.read(job_id, after, int(WAIT_SECONDS * 1000))
            except READ_FAILURES as error:
                logger.warning("job follow outcome=redis_failed type=%s", type(error).__name__)
                await asyncio.sleep(WAIT_SECONDS)  # back off so a Redis outage isn't a busy loop
                entries = []  # falls through to the row check below

            # Step 3: pass each event on and stop at the one that finishes the job
            for event_id, event in entries:
                after = event_id  # the next XREAD starts after this one
                # the id becomes the browser's Last-Event-ID so a reconnect resumes from here
                yield ServerSentEvent(data=event, event=STATUS_EVENT, id=event_id)
                if event.finished:
                    logger.info("job follow ended", extra={"job_id": job_id, "from": "redis"})
                    return  # ends the stream and the client closes its EventSource

            # Step 4: with no events check the row Redis may have lost the event or be down
            # but the row is always right
            if not entries:  # at most one row read per 15 s wait
                latest = await self._latest(job_id, user_id)
                if latest.finished:
                    logger.info("job follow ended", extra={"job_id": job_id, "from": "row"})
                    yield ServerSentEvent(data=latest, event=STATUS_EVENT)
                    return
