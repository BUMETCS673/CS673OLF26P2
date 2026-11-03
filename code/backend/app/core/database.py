"""The async database engine, and a session per request."""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import get_settings


def libpq_url(database_url: str) -> str:
    """The URL in the form psycopg itself takes, for what connects without SQLAlchemy."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


# A filtered vector search keeps walking the HNSW index until enough rows pass the filter. By
# default the index stops at about 40 neighbours, so a filter can leave none. Strict order, because
# near-duplicate checks read only the closest row.
CONNECT_ARGS = {"options": "-c hnsw.iterative_scan=strict_order"}


@lru_cache
def get_engine() -> AsyncEngine:
    """One engine and connection pool per process, created on first use."""
    return create_async_engine(
        get_settings().database_url, pool_pre_ping=True, connect_args=CONNECT_ARGS
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    # Attributes stay loaded after commit, because async code can't load them lazily later.
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """A session for one request, closed when the request ends."""
    async with get_session_factory()() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
