"""Reading a job, and following it live."""

import json

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import update

from app.core.redis import get_redis
from app.jobs import events as job_events
from app.jobs.events import EXPIRE_SECONDS, JobEvents, stream_key
from app.jobs.execution import run_job
from app.models import Job
from app.models.job import DONE, FAILED, QUEUED, RUNNING
from app.repositories.jobs import JobRepository
from app.schemas.jobs import JobEvent
from app.services import jobs as jobs_service
from app.services.jobs import JobService


@pytest.fixture
def make_job(session, me):
    async def _make_job(**fields) -> Job:
        job = Job(user_id=me.id, kind="test", **fields)
        session.add(job)
        await session.commit()
        return job

    return _make_job


@pytest.fixture
async def redis_events():
    """Real streams, removed afterward, since they outlive the test's transaction."""
    used = []

    async def _for_job(job_id) -> JobEvents:
        used.append(stream_key(job_id))
        await get_redis().delete(stream_key(job_id))
        return JobEvents(get_redis())

    yield _for_job
    if used:
        await get_redis().delete(*used)


def _parse(body: str) -> list[dict]:
    """An SSE body as a list of events, each with its id and decoded data."""
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append({"id": fields.get("id"), **json.loads(fields["data"])})
    return events


# --- reading ------------------------------------------------------------------------------


async def test_a_job_can_be_read(client, make_job):
    job = await make_job(status=DONE, result={"cards": 3})

    response = await client.get(f"/api/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["kind"]) == (job.id, "test")
    assert (body["status"], body["result"], body["error"]) == (DONE, {"cards": 3}, None)


async def test_someone_elses_job_doesnt_exist(client, session, make_user, me):
    other = await make_user(email="other@example.com")
    job = Job(user_id=other.id, kind="test")
    session.add(job)
    await session.commit()

    assert (await client.get(f"/api/jobs/{job.id}")).status_code == 404


async def test_a_job_needs_a_signed_in_user(client):
    assert (await client.get("/api/jobs/1")).status_code == 401
    assert (await client.get("/api/jobs/1/events")).status_code == 401


# --- following ----------------------------------------------------------------------------


async def test_following_a_finished_job_sends_its_status_and_ends(client, make_job):
    job = await make_job(status=FAILED, error="Too big.")

    response = await client.get(f"/api/jobs/{job.id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert _parse(response.text) == [
        {"id": None, "status": FAILED, "result": None, "error": "Too big.", "progress": None}
    ]


async def test_following_someone_elses_job_answers_404(client, session, make_user, me):
    other = await make_user(email="other@example.com")
    job = Job(user_id=other.id, kind="test")
    session.add(job)
    await session.commit()

    assert (await client.get(f"/api/jobs/{job.id}/events")).status_code == 404


async def test_following_sends_each_event_and_ends_when_it_finishes(
    client, make_job, redis_events
):
    job = await make_job(status=RUNNING)
    events = await redis_events(job.id)
    await events.publish(job.id, JobEvent(status=RUNNING))
    await events.publish(job.id, JobEvent(status=DONE, result={"cards": 3}))
    await events.publish(job.id, JobEvent(status=RUNNING))  # never reached

    sent = _parse((await client.get(f"/api/jobs/{job.id}/events")).text)

    assert [event["status"] for event in sent] == [RUNNING, RUNNING, DONE]
    assert sent[0]["id"] is None  # the first is the row, which has no place in the stream
    assert sent[2]["result"] == {"cards": 3}


async def test_reconnecting_only_sends_what_was_missed(client, make_job, redis_events):
    job = await make_job(status=RUNNING)
    events = await redis_events(job.id)
    await events.publish(job.id, JobEvent(status=RUNNING))
    await events.publish(job.id, JobEvent(status=DONE))
    first = _parse((await client.get(f"/api/jobs/{job.id}/events")).text)

    response = await client.get(
        f"/api/jobs/{job.id}/events", headers={"Last-Event-ID": first[1]["id"]}
    )

    sent = _parse(response.text)
    assert [event["id"] for event in sent] == [None, first[2]["id"]]


async def test_a_malformed_event_id_is_refused(client, make_job):
    job = await make_job()

    response = await client.get(f"/api/jobs/{job.id}/events", headers={"Last-Event-ID": "nope"})

    assert response.status_code == 422


class _Events:
    """Stands in for Redis, and runs `step` the moment it's read."""

    def __init__(self, step):
        self.step = step

    async def read(self, _job_id, _after, _block_ms):
        await self.step()
        return []


async def _follow(session, job, events) -> list[JobEvent]:
    service = JobService(session, JobRepository(session), events)
    return [sent.data async for sent in service.follow(job.id, job.user_id, "0")]


async def test_a_lost_event_is_caught_by_rereading_the_row(session, session_factory, make_job):
    job = await make_job(status=RUNNING)

    async def finish_without_an_event():
        async with session_factory() as other:
            await other.execute(update(Job).where(Job.id == job.id).values(status=DONE))
            await other.commit()

    sent = await _follow(session, job, _Events(finish_without_an_event))

    assert [event.status for event in sent] == [RUNNING, DONE]


async def test_following_survives_redis_being_down(
    session, session_factory, make_job, monkeypatch
):
    monkeypatch.setattr(jobs_service, "WAIT_SECONDS", 0)
    job = await make_job(status=RUNNING)
    failures = iter([True])

    async def fail_then_finish():
        if next(failures, False):
            raise RedisConnectionError
        async with session_factory() as other:
            await other.execute(update(Job).where(Job.id == job.id).values(status=FAILED))
            await other.commit()

    sent = await _follow(session, job, _Events(fail_then_finish))

    assert [event.status for event in sent] == [RUNNING, FAILED]


# --- publishing ---------------------------------------------------------------------------


async def test_events_expire_and_read_back_in_order(make_job, redis_events):
    job = await make_job()
    events = await redis_events(job.id)

    await events.publish(job.id, JobEvent(status=RUNNING))
    await events.publish(job.id, JobEvent(status=DONE))

    read = await events.read(job.id, job_events.START, 1)
    assert [event.status for _, event in read] == [RUNNING, DONE]
    assert 0 < await get_redis().ttl(stream_key(job.id)) <= EXPIRE_SECONDS


async def test_a_redis_failure_doesnt_fail_the_job(make_job):
    class _Down:
        def pipeline(self):
            raise RedisConnectionError

    job = await make_job()

    await JobEvents(_Down()).publish(job.id, JobEvent(status=RUNNING))


@pytest.fixture
def recorded():
    return []


async def _record(recorded, job_id, event):
    recorded.append((job_id, event.status))


async def test_a_worker_publishes_each_change_after_saving_it(
    session_factory, make_job, recorded
):
    job = await make_job()

    async def publish(job_id, event):
        await _record(recorded, job_id, event)

    async def handler(_):
        return {"cards": 1}

    await run_job(job.id, session_factory, {"test": handler}, publish_event=publish)

    assert recorded == [(job.id, RUNNING), (job.id, DONE)]


async def test_a_retry_tells_followers_its_queued_again(session_factory, make_job, recorded):
    job = await make_job()

    async def publish(job_id, event):
        await _record(recorded, job_id, event)

    async def fail(_):
        raise RuntimeError

    await run_job(job.id, session_factory, {"test": fail}, publish_event=publish)

    assert recorded == [(job.id, RUNNING), (job.id, QUEUED)]


async def test_a_worker_that_lost_its_lease_announces_nothing(session_factory, make_job, recorded):
    job = await make_job()

    async def publish(job_id, event):
        await _record(recorded, job_id, event)

    async def lose_the_lease(_):
        async with session_factory() as other:
            await other.execute(
                update(Job).where(Job.id == job.id).values(status=RUNNING, attempts=2)
            )
            await other.commit()

    await run_job(job.id, session_factory, {"test": lose_the_lease}, publish_event=publish)

    assert recorded == [(job.id, RUNNING)]


async def test_a_handler_can_report_progress(session_factory, make_job):
    job = await make_job()
    sent = []

    async def publish(_, event):
        sent.append(event)

    async def handler(context):
        await context.report({"stage": "reading"})

    await run_job(job.id, session_factory, {"test": handler}, publish_event=publish)

    assert sent[1] == JobEvent(status=RUNNING, progress={"stage": "reading"})
