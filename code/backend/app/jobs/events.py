"""Each job's live events, kept in a Redis Stream so a client that reconnects can catch up.

Postgres holds the truth and is always written first. A lost event only delays what a client
sees, since whoever follows a job also re-reads its row, so failing to publish never fails a job.
"""

import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.schemas.jobs import JobEvent

logger = logging.getLogger(__name__)

START = "0"  # a stream position before every event
MAX_EVENTS = 1000  # approximate, since an exact cap costs Redis more work
EXPIRE_SECONDS = 3600  # after the last event, so finished jobs clean themselves up

READ_FAILURES = (RedisError, OSError)


def stream_key(job_id: int) -> str:
    return f"job:{job_id}:events"


class JobEvents:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def publish(self, job_id: int, event: JobEvent) -> None:
        key = stream_key(job_id)
        try:
            async with self.redis.pipeline() as pipeline:
                pipeline.xadd(
                    key, {"data": event.model_dump_json()}, maxlen=MAX_EVENTS, approximate=True
                )
                pipeline.expire(key, EXPIRE_SECONDS)
                await pipeline.execute()
        except READ_FAILURES as error:
            logger.warning("job event outcome=failed type=%s", type(error).__name__)

    async def read(self, job_id: int, after: str, block_ms: int) -> list[tuple[str, JobEvent]]:
        """Events after a position, waiting up to `block_ms` for one. Empty if none arrives."""
        streams = await self.redis.xread({stream_key(job_id): after}, block=block_ms)
        return [
            (event_id, JobEvent.model_validate_json(fields["data"]))
            for _, entries in streams
            for event_id, fields in entries
        ]
