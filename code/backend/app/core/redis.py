"""The shared Redis client, for job events."""

from functools import lru_cache

from redis.asyncio import Redis

from app.core.settings import get_settings


@lru_cache
def get_redis() -> Redis:
    """One client and connection pool per process, which connects on first use."""
    return Redis.from_url(get_settings().redis_url, decode_responses=True, socket_connect_timeout=5)
