"""The LangGraph checkpointer, which saves paused runs between requests."""

import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

logger = logging.getLogger(__name__)

# Own schema, so `flask db migrate` doesn't see these tables and propose dropping them.
SCHEMA = "langgraph"

# SQLite only: the test suite's database. Doesn't survive restarts or span gunicorn workers.
_memory = InMemorySaver()


@contextmanager
def open_checkpointer(database_url: str) -> Iterator[BaseCheckpointSaver]:
    """Yield a checkpointer for `database_url`, opening a Postgres connection if needed."""
    if not database_url.startswith("postgresql://"):
        yield _memory
        return

    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    separator = "&" if "?" in database_url else "?"
    url = f"{database_url}{separator}options=-csearch_path%3D{SCHEMA}"
    with PostgresSaver.from_conn_string(url) as saver:
        saver.setup()  # idempotent: creates or upgrades LangGraph's tables
        yield saver


def discard_threads(database_url: str, thread_ids: Iterable[str]) -> None:
    """Delete saved runs that are no longer needed. Best effort, since a leftover is harmless."""
    try:
        with open_checkpointer(database_url) as checkpointer:
            for thread_id in thread_ids:
                checkpointer.delete_thread(thread_id)
    except Exception as error:
        logger.warning("leech_doctor outcome=discard_failed type=%s", type(error).__name__)
