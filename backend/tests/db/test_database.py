"""Unit tests for database URL and engine configuration."""

from secrets import token_hex

import pytest

from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.db import (
    DatabaseNotConfiguredError,
    UnsupportedDatabaseDriverError,
    create_database,
    get_database_url,
)


def test_missing_database_url_does_not_create_engine() -> None:
    """Pure unit-test and startup paths can explicitly omit PostgreSQL."""
    settings = Settings.model_validate({"database_url": None})

    assert create_database(settings) is None
    with pytest.raises(DatabaseNotConfiguredError, match="TNPSC_DATABASE_URL"):
        get_database_url(settings)


def test_plain_postgresql_url_is_normalized_to_async_psycopg() -> None:
    """Legacy PostgreSQL schemes use the one supported driver without losing secrets."""
    password = token_hex(16)
    settings = Settings.model_validate(
        {"database_url": f"postgresql://user:{password}@localhost:5432/tnpsc"}
    )

    url = get_database_url(settings)

    assert url.drivername == "postgresql+psycopg"
    assert url.password == password


def test_alternate_postgresql_driver_is_rejected() -> None:
    """The runtime cannot silently introduce a second async driver stack."""
    settings = Settings.model_validate(
        {"database_url": "postgresql+asyncpg://user:password@localhost:5432/tnpsc"}
    )

    with pytest.raises(UnsupportedDatabaseDriverError, match=r"postgresql\+psycopg"):
        get_database_url(settings)


@pytest.mark.anyio
async def test_configured_database_builds_and_disposes_lazy_async_engine() -> None:
    """Engine construction performs no network I/O and owns explicit disposal."""
    settings = Settings.model_validate(
        {"database_url": "postgresql+psycopg://user:password@localhost:5432/tnpsc"}
    )

    database = create_database(settings)

    assert database is not None
    assert database.engine.url.drivername == "postgresql+psycopg"
    await database.close()
