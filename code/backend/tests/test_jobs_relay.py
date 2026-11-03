"""The relay that sends jobs from Postgres to Redis."""

import asyncio
from contextlib import suppress
from datetime import timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from taskiq import TaskiqEvents

from app.jobs.broker import broker
from app.jobs.execution import MAX_ATTEMPTS, SOMETHING_WENT_WRONG
from app.jobs.relay import relay_once, run_relay
from app.jobs.tasks import start_relay, stop_relay
from app.models import Job, User, utcnow
from app.models.job import FAILED, QUEUED, RUNNING
from app.repositories.jobs import JobRepository


@pytest.fixture
def make_job(session, me):
    async def _make_job(**fields) -> Job:
        job = Job(user_id=me.id, kind="test", **fields)
        session.add(job)
        await session.commit()
        return job

    return _make_job


@pytest.fixture
def published():
    return []


@pytest.fixture
def send(session_factory, published):
    async def _publish(job_id):
        published.append(job_id)

    async def _send():
        return await relay_once(session_factory, _publish)

    return _send


async def _reload(session, job_id) -> Job:
    session.expunge_all()
    return await session.scalar(select(Job).where(Job.id == job_id))


async def test_a_new_job_is_sent_and_marked(session, make_job, send, published):
    job = await make_job()

    assert await send() == 1

    assert published == [job.id]
    assert (await _reload(session, job.id)).enqueued_at is not None


async def test_a_sent_job_isnt_sent_again_right_away(make_job, send, published):
    job = await make_job()

    await send()
    await send()

    assert published == [job.id]


async def test_a_job_lost_after_sending_is_sent_again(make_job, send, published):
    job = await make_job(enqueued_at=utcnow() - timedelta(minutes=2))

    await send()

    assert published == [job.id]


async def test_a_running_job_isnt_sent(make_job, send, published):
    await make_job(status=RUNNING, lease_until=utcnow() + timedelta(minutes=2))

    await send()

    assert published == []


async def test_a_retry_waits_for_its_time(make_job, send, published):
    await make_job(retry_at=utcnow() + timedelta(minutes=1))
    due = await make_job(retry_at=utcnow() - timedelta(seconds=1))

    await send()

    assert published == [due.id]


async def test_a_worker_cant_start_a_retry_early(session, make_job):
    job = await make_job(retry_at=utcnow() + timedelta(minutes=1))

    assert await JobRepository(session).claim(job.id, utcnow() + timedelta(minutes=2)) is None


async def test_a_job_stays_unsent_if_redis_fails(session, session_factory, make_job):
    job = await make_job()

    async def fail(_):
        raise ConnectionError

    with pytest.raises(ConnectionError):
        await relay_once(session_factory, fail)

    assert (await _reload(session, job.id)).enqueued_at is None


async def test_an_expired_lease_goes_back_in_the_queue(session, make_job, send, published):
    job = await make_job(status=RUNNING, lease_until=utcnow() - timedelta(seconds=1), attempts=1)

    await send()

    saved = await _reload(session, job.id)
    assert saved.status == QUEUED
    assert saved.lease_until is None
    assert published == [job.id]


async def test_a_job_that_keeps_killing_workers_fails(session, make_job, send, published):
    job = await make_job(
        status=RUNNING, lease_until=utcnow() - timedelta(seconds=1), attempts=MAX_ATTEMPTS
    )

    await send()

    saved = await _reload(session, job.id)
    assert (saved.status, saved.error) == (FAILED, SOMETHING_WENT_WRONG)
    assert published == []


async def test_a_live_lease_is_left_alone(session, make_job, send):
    job = await make_job(status=RUNNING, lease_until=utcnow() + timedelta(minutes=2), attempts=1)

    await send()

    assert (await _reload(session, job.id)).status == RUNNING


def test_workers_start_and_stop_the_relay():
    assert start_relay in broker.event_handlers[TaskiqEvents.WORKER_STARTUP]
    assert stop_relay in broker.event_handlers[TaskiqEvents.WORKER_SHUTDOWN]


# --- real commits: notifications and row locks need separate connections ------------------


@pytest.fixture
async def committed(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = User(email="relay@example.com", password_hash="not-a-real-hash")
        session.add(user)
        await session.commit()

    async def add_job() -> int:
        async with factory() as session:
            job = await JobRepository(session).add(Job(user_id=user.id, kind="test"))
            await session.commit()
            return job.id

    yield factory, add_job

    async with factory() as session:
        await session.execute(delete(User).where(User.id == user.id))  # takes its jobs with it
        await session.commit()


async def test_a_new_job_wakes_the_relay_without_waiting_for_a_poll(engine, committed):
    factory, add_job = committed
    sent = asyncio.Queue()
    url = engine.url.render_as_string(hide_password=False)
    relay = asyncio.create_task(run_relay(url, factory, sent.put, poll_seconds=60))
    try:
        # The relay is listening before it sends anything, so the second job can only be seen
        # through its notification.
        first = await add_job()
        assert await asyncio.wait_for(sent.get(), timeout=5) == first
        second = await add_job()
        assert await asyncio.wait_for(sent.get(), timeout=5) == second
    finally:
        relay.cancel()
        with suppress(asyncio.CancelledError):
            await relay


async def test_two_relays_never_take_the_same_job(committed):
    factory, add_job = committed
    job_id = await add_job()

    async with factory() as first, factory() as second:
        assert await JobRepository(first).due_to_send(10) == [job_id]
        assert await JobRepository(second).due_to_send(10) == []
