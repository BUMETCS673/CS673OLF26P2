"""Claiming and running background jobs."""

import asyncio
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from langsmith.run_helpers import get_current_run_tree, tracing_context
from sqlalchemy import select

from app.ai.models import AIRateLimited
from app.core.errors import InvalidRequest, NotFound
from app.jobs.execution import MAX_ATTEMPTS, SOMETHING_WENT_WRONG, run_job
from app.models import Job, utcnow
from app.models.job import DONE, FAILED, QUEUED, RUNNING
from app.repositories.jobs import JobRepository


@pytest.fixture
def make_job(session, me):
    async def _make_job(kind="test", **fields) -> Job:
        job = Job(user_id=me.id, kind=kind, **fields)
        session.add(job)
        await session.commit()
        return job

    return _make_job


async def _reload(session, job_id) -> Job:
    session.expunge_all()
    return await session.scalar(select(Job).where(Job.id == job_id))


# --- claiming -----------------------------------------------------------------------------


async def test_a_new_job_is_queued_and_unsent(make_job):
    job = await make_job(payload={"topic": "Cells"})

    assert (job.status, job.enqueued_at, job.attempts) == (QUEUED, None, 0)
    assert job.payload == {"topic": "Cells"}


async def test_claiming_takes_a_job_and_starts_its_lease(session, make_job):
    job = await make_job()
    lease = utcnow() + timedelta(minutes=2)

    claimed = await JobRepository(session).claim(job.id, lease)

    assert claimed.id == job.id
    saved = await _reload(session, job.id)
    assert (saved.status, saved.attempts) == (RUNNING, 1)
    assert saved.lease_until == lease


async def test_only_one_claim_wins(session, make_job):
    job = await make_job()
    jobs = JobRepository(session)
    lease = utcnow() + timedelta(minutes=2)

    assert await jobs.claim(job.id, lease) is not None
    assert await jobs.claim(job.id, lease) is None


async def test_a_finished_job_cant_be_claimed(session, make_job):
    job = await make_job(status=DONE)

    assert await JobRepository(session).claim(job.id, utcnow()) is None


async def test_only_the_owner_can_read_a_job(session, make_job, make_user):
    job = await make_job()
    other = await make_user(email="other@example.com")
    jobs = JobRepository(session)

    assert await jobs.get_owned(job.id, other.id) is None
    assert (await jobs.get_owned(job.id, job.user_id)).id == job.id


# --- running ------------------------------------------------------------------------------


async def test_a_handler_runs_and_its_result_is_saved(session, session_factory, make_job):
    job = await make_job(kind="echo", payload={"word": "hi"})
    seen = []

    async def echo(context):
        seen.append((context.job_id, context.user_id, context.payload))
        return {"said": context.payload["word"]}

    await run_job(job.id, session_factory, {"echo": echo})

    saved = await _reload(session, job.id)
    assert seen == [(job.id, job.user_id, {"word": "hi"})]
    assert (saved.status, saved.result, saved.error) == (DONE, {"said": "hi"}, None)


async def test_a_job_is_traced_under_its_kind(session_factory, make_job):
    job = await make_job(kind="echo")
    seen = []

    async def echo(_context):
        seen.append(get_current_run_tree())
        return {}

    with tracing_context(enabled=True, client=MagicMock()):
        await run_job(job.id, session_factory, {"echo": echo})

    assert seen[0].name == "echo"
    assert seen[0].metadata["job_id"] == job.id


async def test_delivering_a_job_twice_runs_it_once(session_factory, make_job):
    job = await make_job()
    runs = []

    async def count(_):
        runs.append(1)

    await run_job(job.id, session_factory, {"test": count})
    await run_job(job.id, session_factory, {"test": count})

    assert len(runs) == 1


async def test_a_temporary_failure_goes_back_in_the_queue(session, session_factory, make_job):
    job = await make_job(enqueued_at=utcnow())

    async def fail(_):
        raise AIRateLimited()

    await run_job(job.id, session_factory, {"test": fail})

    saved = await _reload(session, job.id)
    assert (saved.status, saved.enqueued_at, saved.lease_until) == (QUEUED, None, None)
    assert saved.attempts == 1
    assert saved.retry_at > utcnow()


async def test_a_failure_about_one_input_says_which(session, session_factory, make_job):
    job = await make_job()

    async def fail(_):
        raise InvalidRequest("That file doesn't cover this topic.", "topic")

    await run_job(job.id, session_factory, {"test": fail})

    saved = await _reload(session, job.id)
    assert saved.error == "That file doesn't cover this topic."
    assert saved.result == {"field": "topic"}


async def test_it_stops_retrying_after_the_last_attempt(session, session_factory, make_job):
    job = await make_job(attempts=MAX_ATTEMPTS - 1)

    async def fail(_):
        raise AIRateLimited()

    await run_job(job.id, session_factory, {"test": fail})

    saved = await _reload(session, job.id)
    assert saved.status == FAILED
    assert saved.error == AIRateLimited().message


async def test_an_expected_error_fails_at_once_with_its_message(
    session, session_factory, make_job
):
    job = await make_job()

    async def fail(_):
        raise NotFound("That file doesn't exist any more.")

    await run_job(job.id, session_factory, {"test": fail})

    saved = await _reload(session, job.id)
    assert (saved.status, saved.attempts) == (FAILED, 1)
    assert saved.error == "That file doesn't exist any more."


async def test_an_unexpected_errors_text_is_kept_private(
    session, session_factory, make_job, caplog
):
    job = await make_job(attempts=MAX_ATTEMPTS - 1)

    async def fail(_):
        raise RuntimeError("the learner's private text")

    await run_job(job.id, session_factory, {"test": fail})

    saved = await _reload(session, job.id)
    assert saved.error == SOMETHING_WENT_WRONG
    assert "private" not in caplog.text
    assert "type=RuntimeError" in caplog.text


async def test_a_running_job_keeps_extending_its_lease(session_factory, make_job, monkeypatch):
    job = await make_job()
    extended = asyncio.Event()
    seen = []

    # Recorded, not written: the test's sessions share one connection, which can't run two at once.
    async def record(_, job_id, attempt, lease_until):
        seen.append((job_id, attempt, lease_until > utcnow()))
        extended.set()

    monkeypatch.setattr(JobRepository, "extend_lease", record)

    async def slow(_):
        await asyncio.wait_for(extended.wait(), timeout=5)

    await run_job(job.id, session_factory, {"test": slow}, lease=timedelta(milliseconds=40))

    assert seen[0] == (job.id, 1, True)


async def test_a_worker_that_lost_its_lease_cant_change_the_job(session, make_job):
    job = await make_job()
    jobs = JobRepository(session)
    lease = utcnow() + timedelta(minutes=2)
    await jobs.claim(job.id, lease)
    await jobs.requeue(job.id, 1)
    await jobs.claim(job.id, lease)  # the second attempt is now running

    await jobs.finish(job.id, 1, {"from": "the old worker"})
    await jobs.fail(job.id, 1, "from the old worker")

    saved = await _reload(session, job.id)
    assert (saved.status, saved.attempts, saved.result, saved.error) == (RUNNING, 2, None, None)
