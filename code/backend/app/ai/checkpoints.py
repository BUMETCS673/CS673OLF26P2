"""The LangGraph checkpointer, which saves paused runs and conversations between requests."""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.database import libpq_url

logger = logging.getLogger(__name__)

# Its own schema, so Alembic doesn't see these tables and propose dropping them.
SCHEMA = "langgraph"
POOL_MAX_SIZE = 4  # per process

_pools: dict[str, AsyncConnectionPool] = {}
# One saver per database, so each graph compiles once.
_savers: dict[str, AsyncPostgresSaver] = {}
_pools_lock = asyncio.Lock()  # two first requests at once can't both build a pool


async def _pool_for(database_url: str) -> AsyncConnectionPool:
    """The process's pool for this database, setting up LangGraph's tables the first time."""
    async with _pools_lock:
        # Step 1: reuse the pool if this process already made one
        pool = _pools.get(database_url)
        if pool is not None:  # the common path with no I/O at all
            return pool

        # Step 2: create the schema on a one-off connection outside any pool
        url = libpq_url(database_url)  # psycopg's URL form
        async with await AsyncConnection.connect(url, autocommit=True) as connection:
            await connection.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")  # idempotent

        # Step 3: open a small pool with the settings the saver needs
        pool = AsyncConnectionPool(
            url,
            min_size=1,  # one warm connection so the first save doesn't wait to connect
            max_size=POOL_MAX_SIZE,
            # What the saver needs, and `check` replaces connections the server closed.
            kwargs={
                "autocommit": True,  # the saver manages its own statements
                # no server-side prepared statements so it's safe behind poolers
                "prepare_threshold": 0,
                "row_factory": dict_row,  # the saver reads rows as dicts
                "options": f"-c search_path={SCHEMA}",  # its tables live in their own schema
            },
            check=AsyncConnectionPool.check_connection,  # a quick check on checkout
            open=False,  # opened explicitly below inside the running event loop
        )
        await pool.open()
        # Step 4: create LangGraph's tables and run its migrations once per process
        async with pool.connection() as connection:
            await AsyncPostgresSaver(connection).setup()  # idempotent
        _pools[database_url] = pool
        _savers[database_url] = AsyncPostgresSaver(pool)  # the shared saver on the pool
        return pool


@asynccontextmanager
async def open_checkpointer(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    await _pool_for(database_url)  # cheap after the first call
    yield _savers[database_url]  # nothing to close since the pool lives for the process


async def discard_threads(database_url: str, thread_ids: Iterable[str]) -> None:
    """Delete saved runs that are no longer needed. Best effort, since a leftover is harmless."""
    try:
        async with open_checkpointer(database_url) as checkpointer:
            for thread_id in thread_ids:
                await checkpointer.adelete_thread(thread_id)  # every checkpoint of the thread
    except Exception as error:  # never fails the caller whose own work is already saved
        logger.warning("checkpoints outcome=discard_failed type=%s", type(error).__name__)


async def close_checkpointers() -> None:
    for pool in _pools.values():  # return every connection to Postgres at shutdown
        await pool.close()
    _pools.clear()
    _savers.clear()
