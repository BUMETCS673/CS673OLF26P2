"""Running one job: claim it, keep its lease alive, run its handler, and save the outcome."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
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
from app.repositories.unit_of_work import UnitOfWork, open_unit_of_work
from app.schemas.jobs import JobEvent

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=2)  # a worker silent this long is presumed dead
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
    # seconds spread from quick embeds to 10-minute file indexing for useful percentiles
    explicit_bucket_boundaries_advisory=[0.5, 1, 2.5, 5, 10, 20, 30, 60, 120, 300, 600],
)
# What became of an attempt, by the status it left the job in.
_OUTCOMES = {DONE: "done", QUEUED: "retried", FAILED: "failed"}


@dataclass(frozen=True)
class JobContext:
    """What a handler gets. It opens its own short sessions, so none stays open during AI calls."""

    job_id: int
    user_id: int
    payload: dict[str, Any]  # the JSON the request saved on the job row
    # a factory not a session so each step opens and closes its own
    session_factory: async_sessionmaker[AsyncSession]
    report: Callable[[dict[str, Any]], Awaitable[None]]  # tells whoever is following the job
    attempt: int | None = None  # None when a handler runs without the job system

    def transaction(self) -> AbstractAsyncContextManager[UnitOfWork]:
        return open_unit_of_work(self.session_factory)


Handler = Callable[[JobContext], Awaitable[dict[str, Any] | None]]
PublishEvent = Callable[[int, JobEvent], Awaitable[None]]


async def _no_event(_job_id: int, _event: JobEvent) -> None:
    pass


def _safe_message(error: Exception) -> str:
    """Only messages written for learners. Other errors' text can carry their content."""
    if isinstance(error, AIRateLimited | AIUnavailable | AppError):  # our own wording
        return error.message
    return SOMETHING_WENT_WRONG  # anything else gets a generic message never the raw text


def _is_permanent(error: Exception) -> bool:
    """Returns True for errors a retry can't fix, such as a bad key or a malformed reply."""
    if isinstance(error, AITransient):  # checked first since it's a subclass of AIUnavailable
        return False  # overloaded or a dropped connection is worth another attempt
    # unknown errors (a crash, a database blip) count as temporary and get retried
    return isinstance(error, AppError | AIUnavailable)


def _failure_details(error: Exception) -> dict[str, Any] | None:
    """Which input a failure is about, so a form can show it beside that input."""
    return {"field": error.field} if isinstance(error, AppError) and error.field else None


async def _keep_lease(
    job_id: int, attempt: int, session_factory: async_sessionmaker[AsyncSession], lease: timedelta
) -> None:
    """Keep extending the lease, so only a dead worker's job looks abandoned."""
    while True:  # until run_job cancels it
        # renew at half the lease so one missed renewal still leaves a minute of margin
        await asyncio.sleep(lease.total_seconds() / 2)
        async with open_unit_of_work(session_factory) as tx:  # a short session per renewal
            # fenced by attempt so this old worker never extends a retry's newer lease
            await tx.jobs.extend_lease(job_id, attempt, utcnow() + lease)
            await tx.commit()


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
    with log_fields(job_id=job_id):  # a contextvar inherited by every task started inside
        await _run_job(job_id, session_factory, handlers, lease, publish_event)


async def _run_job(
    job_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    handlers: Mapping[str, Handler],
    lease: timedelta,
    publish_event: PublishEvent,
) -> None:
    # Step 1: claim the job or stop if another worker has it or it's finished
    async with open_unit_of_work(session_factory) as tx:
        # one atomic UPDATE ... RETURNING on queued jobs so of two deliveries one wins
        job: Job | None = await tx.jobs.claim(job_id, utcnow() + lease)
        await tx.commit()  # the claim is visible to other workers right away
        if job is None:  # a duplicate delivery or a retry that isn't due yet
            logger.info("job skipped", extra={"reason": "not_claimable"})
            return

        async def report(progress: dict[str, Any]) -> None:  # handlers call this for progress
            await publish_event(job_id, JobEvent(status=RUNNING, progress=progress))

        context = JobContext(
            job.id, job.user_id, job.payload, session_factory, report, job.attempts
        )
        kind, attempts = job.kind, job.attempts  # plain values stay safe after the session closes
    # Step 2: tag the logs and tell followers the job started
    add_log_fields(kind=kind, attempt=attempts)  # every line from here on carries these
    logger.info("job started")
    await publish_event(job_id, JobEvent(status=RUNNING))

    # Step 3: renew the lease in the background while the handler runs
    keep_lease = asyncio.create_task(_keep_lease(job_id, attempts, session_factory, lease))
    started = time.perf_counter()  # monotonic for the duration metric
    try:
        # Step 4: run the handler for this kind inside one LangSmith trace
        # One trace per attempt, so a job's model calls appear together. The payload's ids, like
        # deck_id or document_id, label it too.
        ids = {
            key: value
            for key, value in context.payload.items()
            if key.endswith("_id") and isinstance(value, int)  # ids only never learner text
        }
        async with labelled_trace(kind, context.user_id, job_id=job_id, attempt=attempts, **ids):
            result = await handlers[kind](context)
    except Exception as error:
        # Step 5a: on failure retry later if it may pass or fail the job for good
        # The type only: an error's text can include what the learner uploaded.
        logger.warning("job outcome=failed kind=%s type=%s", kind, type(error).__name__)
        async with open_unit_of_work(session_factory) as tx:
            if attempts < MAX_ATTEMPTS and not _is_permanent(error):
                event = JobEvent(status=QUEUED)
                # linear backoff of 30 s then 60 s so a rate limit has time to clear
                retry_at = utcnow() + RETRY_DELAY * attempts
                changed = await tx.jobs.requeue(job_id, attempts, retry_at)
            else:  # out of attempts or a retry can't help
                event = JobEvent(
                    status=FAILED, error=_safe_message(error), result=_failure_details(error)
                )
                changed = await tx.jobs.fail(job_id, attempts, event.error, event.result)
            await tx.commit()
    else:
        # Step 5b: on success save the result
        event = JobEvent(status=DONE, result=result)
        async with open_unit_of_work(session_factory) as tx:
            # fenced by attempt so False if the lease was lost and a retry took over
            changed = await tx.jobs.finish(job_id, attempts, result)
            await tx.commit()
    finally:
        keep_lease.cancel()  # whatever happened stop renewing
    # Step 6: record the attempt's outcome and duration for Grafana
    labels = {"kind": kind, "outcome": _OUTCOMES[event.status]}  # done, retried or failed
    JOB_ATTEMPTS.add(1, labels)
    JOB_DURATION.record(time.perf_counter() - started, labels)
    logger.info("job ended", extra={"outcome": labels["outcome"], "applied": changed})

    # Step 7: tell followers only if this worker's write applied
    # Only after the commit, so followers never hear of a status that isn't saved yet.
    if changed:  # a worker that lost its lease stays quiet and the retry speaks instead
        await publish_event(job_id, event)
