"""Calls per minute to each model, shared by every worker through Redis.

Each process holding its own count would let the total grow with the number of workers, so the
next free time for a model is kept in Redis. Google's own limit stays the final word, so if Redis
is down, calls go ahead rather than stop.
"""

import asyncio
import logging

from langchain_core.embeddings import Embeddings
from langchain_core.rate_limiters import BaseRateLimiter
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Atomic, so two workers can't take the same slot, and using Redis's clock, so workers' clocks
# don't matter. Each caller gets its own turn and waits for it, so nobody needs to ask again.
_TAKE_NEXT_TURN = """
local time = redis.call('TIME')
local now = time[1] * 1000 + math.floor(time[2] / 1000)
local turn = math.max(now, tonumber(redis.call('GET', KEYS[1]) or 0))
local wait = turn - now
local max_wait = tonumber(ARGV[3])
if (wait > 0 and ARGV[2] == '0') or (max_wait >= 0 and wait > max_wait) then
    return wait
end
local next_turn = turn + tonumber(ARGV[1])
redis.call('SET', KEYS[1], string.format('%.0f', next_turn), 'PX', next_turn - now + 1000)
return wait
"""


class ModelBusy(Exception):
    """The queue for a model is longer than the caller will wait. No turn was taken."""


class RedisRateLimiter(BaseRateLimiter):
    """Spaces calls evenly, so a minute can never hold more than `per_minute` of them.

    With `max_wait_ms`, a longer queue raises ModelBusy, for a learner who is waiting on the reply.
    """

    def __init__(self, redis: Redis, model: str, per_minute: int, max_wait_ms: int | None = None):
        # Called by its hash, so each call sends a few bytes rather than the script. Redis-py loads
        # the script again by itself if Redis has forgotten it, such as after a restart.
        self.take_next_turn = redis.register_script(_TAKE_NEXT_TURN)
        self.key = f"rate:{model}"
        self.gap_ms = 60_000 // per_minute
        self.max_wait_ms = max_wait_ms

    async def aacquire(self, *, blocking: bool = True) -> bool:
        try:
            wait_ms = await self.take_next_turn(
                keys=[self.key],
                args=[
                    self.gap_ms,
                    int(blocking),
                    -1 if self.max_wait_ms is None else self.max_wait_ms,
                ],
            )
        except (RedisError, OSError) as error:
            logger.warning("rate_limit outcome=redis_failed type=%s", type(error).__name__)
            return True
        if not blocking:
            return wait_ms == 0
        if self.max_wait_ms is not None and wait_ms > self.max_wait_ms:
            raise ModelBusy()
        if wait_ms > 0:
            await asyncio.sleep(wait_ms / 1000)
        return True

    def acquire(self, *, blocking: bool = True) -> bool:
        """Everything here calls models asynchronously, and a sync call shouldn't fail for this."""
        return True


class RateLimitedEmbeddings(Embeddings):
    """LangChain's embeddings have no `rate_limiter` setting, unlike its chat models."""

    def __init__(self, embeddings: Embeddings, limiter: BaseRateLimiter):
        self._embeddings = embeddings
        self._limiter = limiter

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embeddings.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        await self._limiter.aacquire()
        return await self._embeddings.aembed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        await self._limiter.aacquire()
        return await self._embeddings.aembed_query(text)
