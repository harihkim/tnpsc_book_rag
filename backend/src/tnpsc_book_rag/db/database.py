"""Async SQLAlchemy database lifecycle with bounded development defaults."""

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tnpsc_book_rag.config import Settings

_PSYCOPG_DRIVER = "postgresql+psycopg"
_POSTGRESQL_DRIVERS = frozenset({"postgres", "postgresql"})


class DatabaseNotConfiguredError(ValueError):
    """Raised when a database operation requires a missing database URL."""


class UnsupportedDatabaseDriverError(ValueError):
    """Raised when settings select a PostgreSQL driver outside the supported stack."""


class DatabaseLifecycle(Protocol):
    """Small application boundary used by health checks and shutdown."""

    async def is_ready(self) -> bool:
        """Return whether PostgreSQL is reachable and pgvector is installed."""
        ...

    async def close(self) -> None:
        """Release database connections and background resources."""
        ...


@dataclass(frozen=True, slots=True)
class Database:
    """Application-owned async engine and session factory."""

    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]

    async def is_ready(self) -> bool:
        """Check connectivity and the migration-owned pgvector extension."""
        try:
            async with self.engine.connect() as connection:
                installed = await connection.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                )
        except SQLAlchemyError:
            return False
        return bool(installed)

    async def close(self) -> None:
        """Dispose the async connection pool explicitly."""
        await self.engine.dispose()


def get_database_url(settings: Settings) -> URL:
    """Return a password-preserving SQLAlchemy URL using the supported async driver."""
    if settings.database_url is None:
        msg = "TNPSC_DATABASE_URL is required for this operation"
        raise DatabaseNotConfiguredError(msg)

    url = make_url(str(settings.database_url.get_secret_value()))
    if url.drivername in _POSTGRESQL_DRIVERS:
        return url.set(drivername=_PSYCOPG_DRIVER)
    if url.drivername != _PSYCOPG_DRIVER:
        msg = "TNPSC_DATABASE_URL must use the postgresql+psycopg driver"
        raise UnsupportedDatabaseDriverError(msg)
    return url


def create_database(settings: Settings) -> Database | None:
    """Create the lazy async database boundary when a URL is configured."""
    if settings.database_url is None:
        return None

    engine = create_async_engine(
        get_database_url(settings),
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
    )
    return Database(
        engine=engine,
        sessions=async_sessionmaker(engine, expire_on_commit=False),
    )
