"""One Redis reader per process for every followed job, instead of one connection per stream.

A blocking XREAD holds a whole Redis connection while it waits, so each open progress stream used
to cost one. Here each wait registers with the hub, and one loop reads every followed stream in a
single XREAD, then hands each wait only the events newer than its own position.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

from redis.asyncio import Redis

from app.core.redis import get_redis
from app.jobs.events import READ_FAILURES, stream_key
from app.schemas.jobs import JobEvent

logger = logging.getLogger(__name__)

ROUND_MS = 1000  # how long one shared read blocks, so a new wait joins within a second
FAILURE_PAUSE = 1.0  # seconds between reads while Redis is failing

Events = list[tuple[str, JobEvent]]  # (stream id, event), the id being the SSE Last-Event-ID


def _position(event_id: str) -> tuple[int, int]:
    """Stream ids are "milliseconds-sequence", compared as numbers rather than as text."""
    milliseconds, _, sequence = event_id.partition("-")
    return int(milliseconds), int(sequence or 0)


@dataclass(eq=False)
class _Wait:
    job_id: int
    after: str  # the last event this follower has
    result: asyncio.Future = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )


class JobEventHub:
    def __init__(self, redis: Redis):
        self.redis = redis
        self._waits: set[_Wait] = set()
        self._reader: asyncio.Task | None = None

    async def read(self, job_id: int, after: str, block_ms: int) -> Events:
        """Events after a position, waiting up to `block_ms` for one. Empty if none arrives."""
        wait = _Wait(job_id, after)
        self._waits.add(wait)
        if self._reader is None or self._reader.done():
            self._reader = asyncio.create_task(self._read_all())  # runs only while someone waits
        try:
            return await asyncio.wait_for(wait.result, block_ms / 1000)
        except TimeoutError:
            return []
        finally:
            self._waits.discard(wait)

    def _pending(self) -> list[_Wait]:
        return [wait for wait in self._waits if not wait.result.done()]

    async def _read_all(self) -> None:
        """Serve every pending wait, and stop once there are none."""
        while pending := self._pending():
            # Step 1: start each stream at the oldest position one of its waits needs
            streams: dict[str, str] = {}
            for wait in pending:
                key = stream_key(wait.job_id)
                if key not in streams or _position(wait.after) < _position(streams[key]):
                    streams[key] = wait.after

            # Step 2: one blocking read over all of them, passing a failure to every wait
            try:
                found = await self.redis.xread(streams, block=ROUND_MS)
            except READ_FAILURES as error:
                logger.warning("job events outcome=read_failed type=%s", type(error).__name__)
                for wait in self._pending():
                    wait.result.set_exception(error)  # follow() then re-reads the job's row
                await asyncio.sleep(FAILURE_PAUSE)  # so a Redis outage isn't a busy loop
                continue

            # Step 3: give each wait only the events newer than its own position
            by_stream = {
                key: [
                    (event_id, JobEvent.model_validate_json(fields["data"]))  # validated not trusted
                    for event_id, fields in entries
                ]
                for key, entries in found
            }
            for wait in self._pending():
                newer = [
                    (event_id, event)
                    for event_id, event in by_stream.get(stream_key(wait.job_id), [])
                    if _position(event_id) > _position(wait.after)
                ]
                if newer:
                    wait.result.set_result(newer)


# Weak keys, so a closed loop's hub goes with it
_hubs: WeakKeyDictionary[asyncio.AbstractEventLoop, JobEventHub] = WeakKeyDictionary()


def get_event_hub() -> JobEventHub:
    """One hub per event loop, which in the app means one per process."""
    loop = asyncio.get_running_loop()
    if loop not in _hubs:
        _hubs[loop] = JobEventHub(get_redis())
    return _hubs[loop]
