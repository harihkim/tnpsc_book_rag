"""Alembic environment shipped with the application's database package."""

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.db import Base, get_database_url

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without opening a database connection."""
    context.configure(
        url=get_database_url(Settings()),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def apply_migrations(connection: Connection) -> None:
    """Run migrations through an established synchronous adapter connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Open one unpooled async connection for the migration run."""
    engine = create_async_engine(get_database_url(Settings()), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(apply_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
