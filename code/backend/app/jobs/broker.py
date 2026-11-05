"""The Taskiq broker, which carries tasks from Redis to the workers."""

from taskiq_redis import RedisStreamBroker

from app.core.settings import get_settings

# Redis Streams, so a task a dead worker never acknowledged gets delivered again. Results are
# saved in Postgres by the tasks themselves, so there's no result backend.
# consumer groups give each task to one worker
broker = RedisStreamBroker(url=get_settings().redis_url)
