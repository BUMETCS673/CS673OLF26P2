"""Embedding vectors cached in Redis, so identical text is never embedded twice."""

from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import suppress

from langchain_core.stores import ByteStore
from redis.asyncio import Redis
from redis.exceptions import RedisError

CACHE_SECONDS = 30 * 24 * 3600
_PREFIX = "embedding:"
_FAILURES = (RedisError, OSError)


class RedisByteStore(ByteStore):
    """A cache only, so a Redis failure just means embedding again, never a failed job.

    Async only, since everything here runs in async workers.
    """

    def __init__(self, redis: Redis):
        self.redis = redis

    async def amget(self, keys: Sequence[str]) -> list[bytes | None]:
        try:
            values = await self.redis.mget([_PREFIX + key for key in keys])
        except _FAILURES:
            return [None] * len(keys)
        return [value.encode() if isinstance(value, str) else value for value in values]

    async def amset(self, key_value_pairs: Sequence[tuple[str, bytes]]) -> None:
        with suppress(_FAILURES):
            async with self.redis.pipeline(transaction=False) as pipeline:
                for key, value in key_value_pairs:
                    pipeline.set(_PREFIX + key, value, ex=CACHE_SECONDS)
                await pipeline.execute()

    async def amdelete(self, keys: Sequence[str]) -> None:
        with suppress(_FAILURES):
            await self.redis.delete(*[_PREFIX + key for key in keys])

    async def ayield_keys(self, *, prefix: str | None = None) -> AsyncIterator[str]:
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
