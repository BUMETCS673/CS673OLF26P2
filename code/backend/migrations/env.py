"""Alembic's entry point. Runs migrations with the app's async database URL."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.settings import get_settings
from app.models import Base

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

DATABASE_URL = get_settings().database_url

# Managed by LangChain's SQLRecordManager, so a migration shouldn't try to drop it.
EXTERNAL_TABLES = {"upsertion_record"}


def _include_name(name, type_, _parent_names) -> bool:
    return not (type_ == "table" and name in EXTERNAL_TABLES)


def run_migrations_offline() -> None:
    """Write the SQL instead of running it: `alembic upgrade head --sql`."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=Base.metadata,
        literal_binds=True,
        include_name=_include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=Base.metadata, include_name=_include_name
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
