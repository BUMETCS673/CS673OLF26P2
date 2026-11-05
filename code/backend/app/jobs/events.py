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

READ_FAILURES = (RedisError, OSError)  # OSError covers a dropped connection below redis-py


def stream_key(job_id: int) -> str:
    return f"job:{job_id}:events"  # one stream per job so readers never filter others' events


class JobEvents:
    def __init__(self, redis: Redis):
        self.redis = redis  # a shared connection pool made once per process

    async def publish(self, job_id: int, event: JobEvent) -> None:
        key = stream_key(job_id)
        try:
            # Step 1: append the event and refresh the stream's expiry together
            # pipeline sends both commands in 1 round trip as MULTI/EXEC so they apply together
            async with self.redis.pipeline() as pipeline:
                pipeline.xadd(  # queued on the pipeline not sent yet
                    # approximate MAXLEN trims in whole blocks far cheaper than an exact cap
                    key, {"data": event.model_dump_json()}, maxlen=MAX_EVENTS, approximate=True
                )
                pipeline.expire(key, EXPIRE_SECONDS)  # reset on each event so idle streams vanish
                await pipeline.execute()  # the one network round trip
        # Step 2: a failed publish only delays what a follower sees so the job carries on
        except READ_FAILURES as error:
            logger.warning("job event outcome=failed type=%s", type(error).__name__)

    async def read(self, job_id: int, after: str, block_ms: int) -> list[tuple[str, JobEvent]]:
        """Events after a position, waiting up to `block_ms` for one. Empty if none arrives."""
        # XREAD BLOCK holds the call until an event lands or time runs out with no polling
        streams = await self.redis.xread({stream_key(job_id): after}, block=block_ms)
        return [  # flattened to (stream id, event) the id being the SSE Last-Event-ID
            (event_id, JobEvent.model_validate_json(fields["data"]))  # validated not trusted
            for _, entries in streams  # one stream asked for so at most one entry here
            for event_id, fields in entries
        ]
