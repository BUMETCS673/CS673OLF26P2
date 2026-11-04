"""Running one job: claim it, keep its lease alive, run its handler, and save the outcome."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.models import AIRateLimited, AITransient, AIUnavailable
from app.ai.tracing import labelled_trace
from app.core.errors import AppError
from app.core.logs import add_log_fields, log_fields
from app.core.telemetry import meter
from app.models import Job, utcnow
from app.models.job import DONE, FAILED, QUEUED, RUNNING
from app.repositories.jobs import JobRepository
from app.schemas.jobs import JobEvent

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=2)
MAX_ATTEMPTS = 3
RETRY_DELAY = timedelta(seconds=30)  # times the attempts so far, to give a rate limit time to pass
SOMETHING_WENT_WRONG = "Something went wrong. Try again."

JOB_ATTEMPTS = meter.create_counter(
    "cadence.jobs", unit="{job}", description="Job attempts, by kind and outcome."
)
JOB_DURATION = meter.create_histogram(
    "cadence.job.duration",
    unit="s",
    description="How long a job attempt ran.",
    explicit_bucket_boundaries_advisory=[0.5, 1, 2.5, 5, 10, 20, 30, 60, 120, 300, 600],
)
# What became of an attempt, by the status it left the job in.
_OUTCOMES = {DONE: "done", QUEUED: "retried", FAILED: "failed"}


@dataclass(frozen=True)
class JobContext:
    """What a handler gets. It opens its own short sessions, so none stays open during AI calls."""

    job_id: int
    user_id: int
    payload: dict[str, Any]
    session_factory: async_sessionmaker[AsyncSession]
    report: Callable[[dict[str, Any]], Awaitable[None]]  # tells whoever is following the job
    attempt: int | None = None  # None when a handler runs without the job system


Handler = Callable[[JobContext], Awaitable[dict[str, Any] | None]]
PublishEvent = Callable[[int, JobEvent], Awaitable[None]]


async def _no_event(_job_id: int, _event: JobEvent) -> None:
    pass


def _safe_message(error: Exception) -> str:
    """Only messages written for learners. Other errors' text can carry their content."""
    if isinstance(error, AIRateLimited | AIUnavailable | AppError):
        return error.message
    return SOMETHING_WENT_WRONG


def _is_permanent(error: Exception) -> bool:
    """Returns True for errors a retry can't fix, such as a bad key or a malformed reply."""
    if isinstance(error, AITransient):
        return False
    return isinstance(error, AppError | AIUnavailable)


def _failure_details(error: Exception) -> dict[str, Any] | None:
    """Which input a failure is about, so a form can show it beside that input."""
    return {"field": error.field} if isinstance(error, AppError) and error.field else None


async def _keep_lease(
    job_id: int, attempt: int, session_factory: async_sessionmaker[AsyncSession], lease: timedelta
) -> None:
    """Keep extending the lease, so only a dead worker's job looks abandoned."""
    while True:
        await asyncio.sleep(lease.total_seconds() / 2)
        async with session_factory() as session:
            await JobRepository(session).extend_lease(job_id, attempt, utcnow() + lease)
            await session.commit()


async def run_job(
    job_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    handlers: Mapping[str, Handler],
    lease: timedelta = LEASE,
    publish_event: PublishEvent = _no_event,
) -> None:
    """Run a job at most once at a time. Delivering the same job twice is harmless.

    Every line logged meanwhile names the job, and once it's claimed, its kind and attempt.
    """
    with log_fields(job_id=job_id):
        await _run_job(job_id, session_factory, handlers, lease, publish_event)


async def _run_job(
    job_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    handlers: Mapping[str, Handler],
    lease: timedelta,
    publish_event: PublishEvent,
) -> None:
    async with session_factory() as session:
        job: Job | None = await JobRepository(session).claim(job_id, utcnow() + lease)
        await session.commit()
        if job is None:
            return

        async def report(progress: dict[str, Any]) -> None:
            await publish_event(job_id, JobEvent(status=RUNNING, progress=progress))

        context = JobContext(
            job.id, job.user_id, job.payload, session_factory, report, job.attempts
        )
        kind, attempts = job.kind, job.attempts
    add_log_fields(kind=kind, attempt=attempts)
    await publish_event(job_id, JobEvent(status=RUNNING))

    keep_lease = asyncio.create_task(_keep_lease(job_id, attempts, session_factory, lease))
    started = time.perf_counter()
    try:
        # One trace per attempt, so a job's model calls appear together. The payload's ids, like
        # deck_id or document_id, label it too.
        ids = {
            key: value
            for key, value in context.payload.items()
            if key.endswith("_id") and isinstance(value, int)
        }
        async with labelled_trace(kind, context.user_id, job_id=job_id, attempt=attempts, **ids):
            result = await handlers[kind](context)
    except Exception as error:
        # The type only: an error's text can include what the learner uploaded.
        logger.warning("job outcome=failed kind=%s type=%s", kind, type(error).__name__)
        async with session_factory() as session:
            jobs = JobRepository(session)
            if attempts < MAX_ATTEMPTS and not _is_permanent(error):
                event = JobEvent(status=QUEUED)
                changed = await jobs.requeue(job_id, attempts, utcnow() + RETRY_DELAY * attempts)
            else:
                event = JobEvent(
                    status=FAILED, error=_safe_message(error), result=_failure_details(error)
                )
                changed = await jobs.fail(job_id, attempts, event.error, event.result)
            await session.commit()
    else:
        event = JobEvent(status=DONE, result=result)
        async with session_factory() as session:
            changed = await JobRepository(session).finish(job_id, attempts, result)
            await session.commit()
    finally:
        keep_lease.cancel()
    labels = {"kind": kind, "outcome": _OUTCOMES[event.status]}
    JOB_ATTEMPTS.add(1, labels)
    JOB_DURATION.record(time.perf_counter() - started, labels)

    # Only after the commit, so followers never hear of a status that isn't saved yet.
    if changed:
        await publish_event(job_id, event)
