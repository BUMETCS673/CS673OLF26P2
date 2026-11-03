"""The LangGraph checkpointer, which saves paused runs and conversations between requests."""

import logging
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

# Own schema, so `flask db migrate` doesn't see these tables and propose dropping them.
SCHEMA = "langgraph"
POOL_MAX_SIZE = 4  # per worker, so two workers hold at most eight connections

# SQLite only: the test suite's database. Doesn't survive restarts or span gunicorn workers.
_memory = InMemorySaver()

# One per worker process and database. Created on first use, after gunicorn has forked.
_pools: dict[str, ConnectionPool] = {}
_pools_lock = threading.Lock()


def _pool_for(database_url: str) -> ConnectionPool:
    """The worker's connection pool, setting up LangGraph's tables the first time."""
    with _pools_lock:
        pool = _pools.get(database_url)
        if pool is not None:
            return pool

        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

        separator = "&" if "?" in database_url else "?"
        pool = ConnectionPool(
            f"{database_url}{separator}options=-csearch_path%3D{SCHEMA}",
            min_size=1,
            max_size=POOL_MAX_SIZE,
            # PostgresSaver needs these settings. check replaces connections the server closed.
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            check=ConnectionPool.check_connection,
            open=True,
        )
        with pool.connection() as connection:
            PostgresSaver(connection).setup()
        _pools[database_url] = pool
        return pool


@contextmanager
def open_checkpointer(database_url: str) -> Iterator[BaseCheckpointSaver]:
    """Yield a checkpointer for `database_url`."""
    if not database_url.startswith("postgresql://"):
        yield _memory
        return
    yield PostgresSaver(_pool_for(database_url))


def discard_threads(database_url: str, thread_ids: Iterable[str]) -> None:
    """Delete saved runs that are no longer needed. Best effort, since a leftover is harmless."""
    try:
        with open_checkpointer(database_url) as checkpointer:
            for thread_id in thread_ids:
                checkpointer.delete_thread(thread_id)
    except Exception as error:
        logger.warning("leech_doctor outcome=discard_failed type=%s", type(error).__name__)
