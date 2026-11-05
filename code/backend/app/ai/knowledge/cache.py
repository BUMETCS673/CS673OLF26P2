"""Embedding vectors cached in Redis, so identical text is never embedded twice."""

from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import suppress

from langchain_core.stores import ByteStore
from redis.asyncio import Redis
from redis.exceptions import RedisError

CACHE_SECONDS = 30 * 24 * 3600  # 30 days so unused vectors expire on their own
_PREFIX = "embedding:"  # keeps these keys apart from the queue and rate limits
_FAILURES = (RedisError, OSError)  # OSError covers a dropped connection


class RedisByteStore(ByteStore):
    """A cache only, so a Redis failure just means embedding again, never a failed job.

    Async only, since everything here runs in async workers.
    """

    def __init__(self, redis: Redis):
        self.redis = redis

    async def amget(self, keys: Sequence[str]) -> list[bytes | None]:
        try:
            values = await self.redis.mget([_PREFIX + key for key in keys])  # one round trip
        except _FAILURES:
            return [None] * len(keys)  # every key a miss so the vectors are just made again
        # the shared client decodes replies to str so turn them back into bytes
        return [value.encode() if isinstance(value, str) else value for value in values]

    async def amset(self, key_value_pairs: Sequence[tuple[str, bytes]]) -> None:
        with suppress(_FAILURES):  # a failed write only costs a later cache miss
            # batching all the SETs into one round trip on one connection with no MULTI/EXEC
            async with self.redis.pipeline(transaction=False) as pipeline:
                for key, value in key_value_pairs:
                    pipeline.set(_PREFIX + key, value, ex=CACHE_SECONDS)  # queued not sent yet
                await pipeline.execute()

    async def amdelete(self, keys: Sequence[str]) -> None:
        with suppress(_FAILURES):
            await self.redis.delete(*[_PREFIX + key for key in keys])  # one DEL for all keys

    async def ayield_keys(self, *, prefix: str | None = None) -> AsyncIterator[str]:
        # SCAN walks the keys in small steps unlike KEYS which blocks Redis
        async for key in self.redis.scan_iter(match=f"{_PREFIX}{prefix or ''}*"):
            yield key.removeprefix(_PREFIX)

    def mget(self, keys: Sequence[str]) -> list[bytes | None]:
        raise NotImplementedError

    def mset(self, key_value_pairs: Sequence[tuple[str, bytes]]) -> None:
        raise NotImplementedError

    def mdelete(self, keys: Sequence[str]) -> None:
        raise NotImplementedError

    def yield_keys(self, *, prefix: str | None = None) -> Iterator[str]:
        raise NotImplementedError
