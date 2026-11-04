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
_pools_lock = asyncio.Lock()


async def _pool_for(database_url: str) -> AsyncConnectionPool:
    """The process's pool for this database, setting up LangGraph's tables the first time."""
    async with _pools_lock:
        pool = _pools.get(database_url)
        if pool is not None:
            return pool

        url = libpq_url(database_url)
        async with await AsyncConnection.connect(url, autocommit=True) as connection:
            await connection.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

        pool = AsyncConnectionPool(
            url,
            min_size=1,
            max_size=POOL_MAX_SIZE,
            # What the saver needs, and `check` replaces connections the server closed.
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
                "options": f"-c search_path={SCHEMA}",
            },
            check=AsyncConnectionPool.check_connection,
            open=False,
        )
        await pool.open()
        async with pool.connection() as connection:
            await AsyncPostgresSaver(connection).setup()
        _pools[database_url] = pool
        _savers[database_url] = AsyncPostgresSaver(pool)
        return pool


@asynccontextmanager
async def open_checkpointer(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    await _pool_for(database_url)
    yield _savers[database_url]


async def discard_threads(database_url: str, thread_ids: Iterable[str]) -> None:
    """Delete saved runs that are no longer needed. Best effort, since a leftover is harmless."""
    try:
        async with open_checkpointer(database_url) as checkpointer:
            for thread_id in thread_ids:
                await checkpointer.adelete_thread(thread_id)
    except Exception as error:
        logger.warning("checkpoints outcome=discard_failed type=%s", type(error).__name__)


async def close_checkpointers() -> None:
    for pool in _pools.values():
        await pool.close()
    _pools.clear()
    _savers.clear()
