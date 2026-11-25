"""Hourly limits on OAuth client registration because anyone can call it without signing in."""

import logging
import time

from redis.exceptions import RedisError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.addresses import client_address
from app.core.redis import get_redis
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 3600
TOO_MANY = "Too many app registrations. Try again later."


async def _allowed(address: str) -> bool:
    # Step 1: name this hour's counters for the caller and the whole site
    settings = get_settings()
    window = int(time.time()) // WINDOW_SECONDS  # a fixed hourly window per key
    keys = {
        f"oauth:register:{address}:{window}": settings.oauth_registrations_per_address_hourly,
        f"oauth:register:site:{window}": settings.oauth_registrations_hourly,
    }
    # Step 2: count this call in both and read the totals back
    try:
        pipe = get_redis().pipeline()  # INCR and EXPIRE for both keys in one round trip
        for key in keys:
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS, nx=True)  # the first call in a window sets its expiry
        counts = (await pipe.execute())[::2]  # every other result is an INCR total
    except RedisError:
        # a Redis outage lets registrations through like the model rate limits do
        logger.warning("registration limit skipped", extra={"reason": "redis_error"})
        return True
    # Step 3: allow the call only while both totals are within their limits
    return all(count <= limit for count, limit in zip(counts, keys.values(), strict=True))


class RegistrationLimit:
    """Wraps the SDK's /register endpoint and answers 429 once a limit is reached."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # CORS preflights pass freely
        if (
            scope["type"] == "http"
            and scope["method"] == "POST"
            # the address can be faked, so the site-wide limit is what really caps the total
            and not await _allowed(client_address(scope))
        ):
            logger.info("registration refused", extra={"reason": "rate_limited"})
            response = JSONResponse(
                {"error": "rate_limited", "error_description": TOO_MANY},
                status_code=429,
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )
            await response(scope, receive, send)  # 429 to the client
            return
        await self.app(scope, receive, send)  # the SDK registers the client
