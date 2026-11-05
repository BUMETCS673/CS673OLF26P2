"""Calls per minute to each model, shared by every worker through Redis.

Each process holding its own count would let the total grow with the number of workers, so the
next free time for a model is kept in Redis. Google's own limit stays the final word, so if Redis
is down, calls go ahead rather than stop.
"""

import asyncio
import logging

from langchain_core.rate_limiters import BaseRateLimiter
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Atomic, so two workers can't take the same slot, and using Redis's clock, so workers' clocks
# don't matter. Each caller gets its own turn and waits for it, so nobody needs to ask again.
_TAKE_NEXT_TURN = """
-- Step 1: read Redis's clock, in milliseconds
local time = redis.call('TIME')
local now = time[1] * 1000 + math.floor(time[2] / 1000)
-- Step 2: this caller's turn is the next free slot, or now if the model is idle
local turn = math.max(now, tonumber(redis.call('GET', KEYS[1]) or 0))
local wait = turn - now
local max_wait = tonumber(ARGV[3])
-- Step 3: a non-blocking caller, or one that won't wait this long, takes no slot
if (wait > 0 and ARGV[2] == '0') or (max_wait >= 0 and wait > max_wait) then
    return wait
end
-- Step 4: reserve the slot by moving the next free time one gap later
local next_turn = turn + tonumber(ARGV[1])
-- PX: the key expires a second after its last slot, so idle models leave nothing behind
redis.call('SET', KEYS[1], string.format('%.0f', next_turn), 'PX', next_turn - now + 1000)
return wait
"""


class ModelBusy(Exception):
    """The queue for a model is longer than the caller will wait. No turn was taken."""


class RedisRateLimiter(BaseRateLimiter):  # plugs into LangChain's rate_limiter= parameter
    """Spaces calls evenly, so a minute can never hold more than `per_minute` of them.

    With `max_wait_ms`, a longer queue raises ModelBusy, for a learner who is waiting on the reply.
    """

    def __init__(self, redis: Redis, model: str, per_minute: int, max_wait_ms: int | None = None):
        # Called by its hash, so each call sends a few bytes rather than the script. Redis-py loads
        # the script again by itself if Redis has forgotten it, such as after a restart.
        self.take_next_turn = redis.register_script(_TAKE_NEXT_TURN)  # EVALSHA else EVAL
        self.key = f"rate:{model}"  # one key per model shared by every process
        # even spacing instead of a window so no burst at the start of each minute
        self.gap_ms = 60_000 // per_minute
        self.max_wait_ms = max_wait_ms  # None lets background work wait as long as it takes

    async def aacquire(self, *, blocking: bool = True) -> bool:
        # Step 1: take a turn from Redis in one atomic script call
        try:
            wait_ms = await self.take_next_turn(
                keys=[self.key],
                args=[
                    self.gap_ms,
                    int(blocking),  # Lua sees strings so '1' or '0'
                    -1 if self.max_wait_ms is None else self.max_wait_ms,  # -1 means no cap
                ],
            )
        except (RedisError, OSError) as error:
            logger.warning("rate_limit outcome=redis_failed type=%s", type(error).__name__)
            return True  # fail open since Google's own limit still applies
        # Step 2: answer a non-blocking check without waiting
        if not blocking:
            return wait_ms == 0
        # Step 3: refuse a wait longer than the learner should sit through
        if self.max_wait_ms is not None and wait_ms > self.max_wait_ms:
            raise ModelBusy()  # a fallback error so the next model in the chain is tried
        # Step 4: sleep until the reserved turn without blocking the event loop
        if wait_ms > 0:
            await asyncio.sleep(wait_ms / 1000)
        return True

    def acquire(self, *, blocking: bool = True) -> bool:
        """Everything here calls models asynchronously, and a sync call shouldn't fail for this."""
        return True
