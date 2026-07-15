"""Real-PostgreSQL verification for migration repeatability and readiness."""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.db import create_database

_BACKEND_ROOT = Path(__file__).parents[2]


def _test_database_url() -> str:
    value = os.environ.get("TNPSC_TEST_DATABASE_URL")
    if not value:
        pytest.skip("TNPSC_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


def _alembic_config() -> Config:
    return Config(str(_BACKEND_ROOT / "alembic.ini"))


async def _database_is_ready(settings: Settings) -> bool:
    database = create_database(settings)
    assert database is not None
    try:
        return await database.is_ready()
    finally:
        await database.close()


@pytest.mark.postgres
def test_pgvector_migration_up_down_and_up_is_repeatable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The baseline migration can rebuild pgvector on a disposable database."""
    database_url = _test_database_url()
    monkeypatch.setenv("TNPSC_DATABASE_URL", database_url)
    settings = Settings.model_validate({"database_url": database_url})
    config = _alembic_config()

    command.downgrade(config, "base")
    assert asyncio.run(_database_is_ready(settings)) is False

    command.upgrade(config, "head")
    assert asyncio.run(_database_is_ready(settings)) is True

    command.downgrade(config, "base")
    assert asyncio.run(_database_is_ready(settings)) is False

    command.upgrade(config, "head")
    assert asyncio.run(_database_is_ready(settings)) is True
