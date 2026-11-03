"""Queries for background jobs."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Update, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, utcnow
from app.models.job import DONE, FAILED, JOBS_CHANNEL, QUEUED, RUNNING

RESEND_AFTER = timedelta(minutes=1)  # still queued this long after sending means it was lost


def _retry_is_due(now: datetime) -> ColumnElement[bool]:
    return or_(Job.retry_at.is_(None), Job.retry_at <= now)


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, job: Job) -> Job:
        """Save a job and announce it. Postgres only delivers the notice if the commit succeeds."""
        self.session.add(job)
        await self.session.flush()
        await self.session.execute(select(func.pg_notify(JOBS_CHANNEL, "")))
        return job

    async def count_unfinished(self, user_id: int, kind: str) -> int:
        return await self.session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.user_id == user_id, Job.kind == kind, Job.status.in_((QUEUED, RUNNING)))
        )

    async def get(self, job_id: int) -> Job | None:
        return await self.session.get(Job, job_id)

    async def get_owned(self, job_id: int, user_id: int) -> Job | None:
        return await self.session.scalar(
            select(Job).where(Job.id == job_id, Job.user_id == user_id)
        )

    async def holds_attempt(self, job_id: int, attempt: int) -> bool:
        """Whether no retry has taken over. The lock stops one starting until the caller commits."""
        current = await self.session.scalar(
            select(Job.attempts).where(Job.id == job_id).with_for_update()
        )
        return current == attempt

    async def claim(self, job_id: int, lease_until: datetime) -> Job | None:
        """Take a queued job atomically. None means another worker has it, or it's finished."""
        return await self.session.scalar(
            update(Job)
            .where(Job.id == job_id, Job.status == QUEUED, _retry_is_due(utcnow()))
            .values(status=RUNNING, lease_until=lease_until, attempts=Job.attempts + 1)
            .returning(Job)
        )

    # A worker that lost its lease must not touch the job's later attempt, so each write below
    # only applies to the attempt that worker claimed.
    def _current(self, job_id: int, attempt: int) -> Update:
        return update(Job).where(Job.id == job_id, Job.status == RUNNING, Job.attempts == attempt)

    async def _change(self, job_id: int, attempt: int, **values: Any) -> bool:
        """Whether the write applied, so a worker that lost its lease can stay quiet."""
        result = await self.session.execute(self._current(job_id, attempt).values(**values))
        return result.rowcount == 1

    async def extend_lease(self, job_id: int, attempt: int, lease_until: datetime) -> None:
        await self._change(job_id, attempt, lease_until=lease_until)

    async def finish(self, job_id: int, attempt: int, result: dict[str, Any] | None) -> bool:
        return await self._change(job_id, attempt, status=DONE, result=result, error=None)

    async def fail(
        self, job_id: int, attempt: int, error: str, result: dict[str, Any] | None = None
    ) -> bool:
        return await self._change(job_id, attempt, status=FAILED, error=error, result=result)

    async def requeue(self, job_id: int, attempt: int, retry_at: datetime | None = None) -> bool:
        """Back in line. Clearing `enqueued_at` tells the relay to send it again."""
        return await self._change(
            job_id, attempt, status=QUEUED, enqueued_at=None, lease_until=None, retry_at=retry_at
        )

    async def due_to_send(self, limit: int) -> list[int]:
        """Lock what's due until the commit. `SKIP LOCKED` leaves other relays different rows."""
        now = utcnow()
        job_ids = await self.session.scalars(
            select(Job.id)
            .where(
                Job.status == QUEUED,
                _retry_is_due(now),
                or_(Job.enqueued_at.is_(None), Job.enqueued_at < now - RESEND_AFTER),
            )
            .order_by(Job.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(job_ids)

    async def mark_sent(self, job_ids: list[int]) -> None:
        if job_ids:
            await self.session.execute(
                update(Job).where(Job.id.in_(job_ids)).values(enqueued_at=utcnow())
            )

    async def recover_expired(self, max_attempts: int, error: str) -> None:
        """Handle jobs whose worker died. Too many attempts means the job itself is the cause."""
        expired = update(Job).where(Job.status == RUNNING, Job.lease_until < utcnow())
        await self.session.execute(
            expired.where(Job.attempts >= max_attempts).values(status=FAILED, error=error)
        )
        await self.session.execute(
            expired.where(Job.attempts < max_attempts).values(
                status=QUEUED, enqueued_at=None, lease_until=None
            )
        )
