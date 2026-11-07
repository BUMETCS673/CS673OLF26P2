"""Hourly cleanup of OAuth rows nobody can use any more. It runs beside the worker's tasks.

Every worker process runs it. The deletes don't depend on each other and repeating them is safe.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import utcnow
from app.repositories.unit_of_work import open_unit_of_work

logger = logging.getLogger(__name__)

CLEANUP_SECONDS = 3600
# enough time to finish a sign-in before an abandoned client is deleted
UNUSED_CLIENT_AGE = timedelta(days=1)


async def clean_oauth(session_factory: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    """Delete expired token pairs and clients that never got a token. Returns both counts."""
    now = utcnow()
    async with open_unit_of_work(session_factory) as tx:  # a session outside any request
        # Step 1: delete token pairs that can't refresh any more
        tokens = await tx.oauth_tokens.delete_expired(now)
        # Step 2: delete clients that registered a day ago and never got a token
        clients = await tx.oauth_clients.delete_unused(now - UNUSED_CLIENT_AGE)
        await tx.commit()  # both deletes save together
    logger.info("oauth cleanup done", extra={"tokens": tokens, "clients": clients})
    return tokens, clients


async def run_cleanup(session_factory: async_sessionmaker[AsyncSession]) -> None:
    while True:  # until the worker cancels it at shutdown
        try:
            await clean_oauth(session_factory)
        except Exception:  # caught broadly so one failure doesn't stop every later run
            logger.exception("oauth cleanup failed")
        await asyncio.sleep(CLEANUP_SECONDS)
