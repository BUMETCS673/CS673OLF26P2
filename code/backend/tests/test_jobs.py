"""The task broker and worker setup."""

from taskiq_redis import RedisStreamBroker

from app.core.settings import Settings
from app.jobs.broker import broker
from app.jobs.tasks import ping


def test_tasks_use_a_broker_that_acknowledges_them():
    assert isinstance(broker, RedisStreamBroker)


async def test_a_task_can_run_directly():
    assert await ping.original_func() == "pong"


def test_the_redis_url_is_a_setting(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://example:6379/1")

    assert Settings().redis_url == "redis://example:6379/1"
