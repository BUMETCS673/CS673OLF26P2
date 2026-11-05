"""The relay: the only thing that sends jobs to Redis, reading them from the `jobs` table.

A job is saved in the same transaction as the work that asked for it, then sent from here. If
Redis is down or loses its data, the rows are still here, and the job is simply sent again.
Sending can repeat, which is safe because only one worker can claim a job.

It runs inside each worker process. Several relays can run at once, since `SKIP LOCKED` gives each
one different rows.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from psycopg import AsyncConnection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import libpq_url
from app.jobs.execution import MAX_ATTEMPTS, SOMETHING_WENT_WRONG
from app.models.job import JOBS_CHANNEL
from app.repositories.jobs import JobRepository

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
POLL_SECONDS = 5.0  # the backstop for what a notification can't announce, like an expired lease

Publish = Callable[[int], Awaitable[None]]


async def relay_once(session_factory: async_sessionmaker[AsyncSession], publish: Publish) -> int:
    """Recover abandoned jobs, then send what's due. Returns how many jobs were sent.

    If sending fails, everything rolls back and is sent again later, including any jobs that did
    reach Redis, because a repeat is harmless and a lost job isn't.
    """
    async with session_factory() as session:  # one transaction for the whole batch
        jobs = JobRepository(session)
        # Step 1: requeue jobs whose worker died (lease expired) or fail them past 3 attempts
        await jobs.recover_expired(MAX_ATTEMPTS, SOMETHING_WENT_WRONG)  # two set-based UPDATEs
        # Step 2: lock up to 100 jobs due to send
        # FOR UPDATE SKIP LOCKED gives other workers' relays other rows with no waiting
        job_ids = await jobs.due_to_send(BATCH_SIZE)
        # Step 3: send them to the Redis queue all at once
        # Sent concurrently, so a batch costs about one Redis round trip rather than one per job.
        await asyncio.gather(*(publish(job_id) for job_id in job_ids))
        # Step 4: mark them sent then commit which also releases the row locks
        await jobs.mark_sent(job_ids)  # one UPDATE ... WHERE id IN (...)
        # a crash before this resends so delivery is at-least-once and never lost
        await session.commit()
    return len(job_ids)  # a full batch means more may be waiting


async def run_relay(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    publish: Publish,
    poll_seconds: float = POLL_SECONDS,
) -> None:
    """Run until cancelled, waking on each new job, or after `poll_seconds` if none arrives."""
    # LISTEN needs one connection kept open, outside the pool.
    conninfo = libpq_url(database_url)  # psycopg's own URL form without SQLAlchemy's driver
    while True:  # reconnects after any failure
        try:
            # Step 1: open the listening connection with autocommit so LISTEN takes effect at once
            async with await AsyncConnection.connect(conninfo, autocommit=True) as listener:
                # each job's INSERT runs pg_notify on this channel delivered when it commits
                await listener.execute(f"LISTEN {JOBS_CHANNEL}")
                while True:
                    # Step 2: send a batch and go again if it was full
                    if await relay_once(session_factory, publish) == BATCH_SIZE:
                        continue  # there may be more waiting
                    # Step 3: sleep until a notification or 5 s whichever comes first
                    # a notification sends a new job within milliseconds and the 5 s backstop
                    # catches what no notice announces like a lease expiring
                    async for _ in listener.notifies(timeout=poll_seconds, stop_after=1):
                        pass  # the notice's content doesn't matter only that it woke us
        except Exception as error:  # broad on purpose so the relay never stops
            # Postgres or Redis is down. Keep trying, since workers are useless until it's back.
            logger.warning("relay outcome=failed type=%s", type(error).__name__)
            await asyncio.sleep(poll_seconds)  # back off so an outage isn't a busy loop
