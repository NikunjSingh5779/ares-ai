"""Alembic async migration environment.

Uses the async engine from database.connection so Alembic
can run migrations against the same database config as the app.
"""

import asyncio
from logging.config import fileConfig
from alembic import context
from sqlalchemy import pool

from configs.settings import settings
from database.connection import engine  # noqa: F401 — keeps engine importable

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set the database URL from settings (overrides alembic.ini)
config.set_main_option("sqlalchemy.url", settings.database_url)

# Import all models so Alembic can detect schema changes
# Currently no ORM models — schema is managed via raw SQL migrations

target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using async engine."""
    from sqlalchemy.ext.asyncio import create_async_engine

    connectable = create_async_engine(
        settings.database_url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
