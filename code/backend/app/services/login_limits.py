"""Limits on failed sign-ins per email and per address, so passwords can't be guessed at speed."""

import hashlib
import logging
import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.errors import BudgetExceeded
from app.core.settings import Settings

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 15 * 60
TOO_MANY = "Too many sign-in attempts. Try again in 15 minutes."


class LoginLimit:
    """Counts only failures. A Redis outage lets sign-ins through, like the other limits."""

    def __init__(self, redis: Redis, settings: Settings):
        self.redis = redis
        self.settings = settings

    def _keys(self, email: str, address: str) -> dict[str, int]:
        """This window's two counters and their limits, the email's first."""
        window = int(time.time()) // WINDOW_SECONDS  # fixed 15-minute windows
        email_hash = hashlib.sha256(email.encode()).hexdigest()[:32]  # Redis never holds the email
        return {
            # the email's counter can't be dodged by faking the address
            f"login:failed:email:{email_hash}:{window}": self.settings.login_failures_per_email,
            # higher since many learners can share one address, like a campus network
            f"login:failed:address:{address}:{window}": self.settings.login_failures_per_address,
        }

    async def check(self, email: str, address: str) -> None:
        """Refuse once either counter is full, before the password is even checked."""
        keys = self._keys(email, address)
        try:
            counts = await self.redis.mget(list(keys))
        except RedisError:
            logger.warning("login limit skipped", extra={"reason": "redis_error"})
            return
        if any(int(n or 0) >= limit for n, limit in zip(counts, keys.values(), strict=True)):
            logger.info("login refused", extra={"reason": "rate_limited"})
            raise BudgetExceeded(TOO_MANY)  # 429

    async def record_failure(self, email: str, address: str) -> None:
        try:
            pipe = self.redis.pipeline()  # INCR and EXPIRE for both keys in one round trip
            for key in self._keys(email, address):
                pipe.incr(key)
                pipe.expire(key, WINDOW_SECONDS, nx=True)  # the first failure sets the expiry
            await pipe.execute()
        except RedisError:
            logger.warning("login failure not counted", extra={"reason": "redis_error"})

    async def clear(self, email: str, address: str) -> None:
        """A sign-in resets the email's count but not the address's, which others may share."""
        email_key = next(iter(self._keys(email, address)))
        try:
            await self.redis.delete(email_key)
        except RedisError:
            logger.warning("login limit not cleared", extra={"reason": "redis_error"})
