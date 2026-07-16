"""Real-PostgreSQL verification for migration repeatability and readiness."""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from tnpsc_book_rag.catalog.models import AssetType, ChunkContentType
from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.db import (
    EMBEDDING_DIMENSION,
    AssetRecord,
    BookDocumentRecord,
    BookRecord,
    ChunkEmbeddingRecord,
    ChunkPageRecord,
    ChunkRecord,
    IdempotencyRecord,
    IngestionRunRecord,
    PageRecord,
    create_database,
)

_BACKEND_ROOT = Path(__file__).parents[2]
_CONTENT_TABLES = {
    "assets",
    "book_documents",
    "books",
    "chunk_embeddings",
    "chunk_pages",
    "chunks",
    "ingestion_runs",
    "idempotency_records",
    "pages",
}


@dataclass(frozen=True, slots=True)
class SchemaSummary:
    """Small database-introspection result used by the migration gate."""

    tables: frozenset[str]
    vector_type: str | None
    indexes: dict[str, str]


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


async def _schema_summary(settings: Settings) -> SchemaSummary:
    database = create_database(settings)
    assert database is not None
    try:
        async with database.engine.connect() as connection:
            table_rows = await connection.scalars(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema()"
                )
            )
            vector_type = await connection.scalar(
                text(
                    "SELECT format_type(attribute.atttypid, attribute.atttypmod) "
                    "FROM pg_attribute AS attribute "
                    "JOIN pg_class AS relation ON relation.oid = attribute.attrelid "
                    "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = current_schema() "
                    "AND relation.relname = 'chunk_embeddings' "
                    "AND attribute.attname = 'embedding'"
                )
            )
            index_rows = await connection.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema()"
                )
            )
            return SchemaSummary(
                tables=frozenset(str(name) for name in table_rows),
                vector_type=None if vector_type is None else str(vector_type),
                indexes={str(name): str(definition) for name, definition in index_rows.tuples()},
            )
    finally:
        await database.close()


async def _round_trip_full_content_graph(settings: Settings) -> None:
    """Prove the ORM types can write every table created by the migration."""
    database = create_database(settings)
    assert database is not None
    try:
        async with database.sessions() as session:
            book = BookRecord(
                title="Migration fixture",
                standard=6,
                subject="Science",
                publisher="Tamil Nadu Textbook Corporation",
            )
            session.add(book)
            await session.flush()

            document = BookDocumentRecord(
                book_id=book.id,
                edition="2026",
                source_filename="fixture.pdf",
                source_artifact_key="sources/fixture.pdf",
                source_sha256="a" * 64,
                file_size_bytes=1024,
            )
            session.add(document)
            await session.flush()

            ingestion_run = IngestionRunRecord(document_id=document.id)
            session.add(ingestion_run)
            await session.flush()

            page = PageRecord(
                document_id=document.id,
                ingestion_run_id=ingestion_run.id,
                pdf_page_index=0,
                raw_text="Matter occupies space.",
                normalized_text="Matter occupies space.",
            )
            session.add(page)
            await session.flush()

            asset = AssetRecord(
                page_id=page.id,
                ingestion_run_id=ingestion_run.id,
                asset_type=AssetType.FIGURE,
                artifact_key="assets/figure.png",
                mime_type="image/png",
                sha256="b" * 64,
            )
            chunk = ChunkRecord(
                page_id=page.id,
                document_id=document.id,
                ingestion_run_id=ingestion_run.id,
                sequence_number=0,
                display_text="Matter occupies space.",
                embedding_text="Science: Matter occupies space.",
                content_type=ChunkContentType.PROSE,
                token_count=4,
                content_sha256="c" * 64,
            )
            session.add_all((asset, chunk))
            await session.flush()

            chunk_page = ChunkPageRecord(
                chunk_id=chunk.id,
                page_id=page.id,
                span_order=0,
            )
            embedding = ChunkEmbeddingRecord(
                chunk_id=chunk.id,
                model_identifier="BAAI/bge-small-en-v1.5",
                model_revision="fixture-revision",
                content_sha256=chunk.content_sha256,
                embedding=[0.0] * EMBEDDING_DIMENSION,
            )
            session.add_all((chunk_page, embedding))
            await session.flush()

            idempotency = IdempotencyRecord(
                key="migration-fixture-key",
                operation="POST /v1/books",
                request_sha256="d" * 64,
                response_status=201,
                response_body={"id": str(book.id)},
                response_headers={"Location": f"/v1/books/{book.id}"},
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            session.add(idempotency)
            await session.flush()

            embedding_count = await session.scalar(
                select(func.count()).select_from(ChunkEmbeddingRecord)
            )
            assert embedding_count == 1
            await session.rollback()
    finally:
        await database.close()


@pytest.mark.postgres
def test_content_schema_migration_up_down_and_up_is_repeatable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complete initial schema can rebuild and accept a full content graph."""
    database_url = _test_database_url()
    monkeypatch.setenv("TNPSC_DATABASE_URL", database_url)
    settings = Settings.model_validate({"database_url": database_url})
    config = _alembic_config()

    command.downgrade(config, "base")
    assert asyncio.run(_database_is_ready(settings)) is False

    command.upgrade(config, "head")
    assert asyncio.run(_database_is_ready(settings)) is True
    first_schema = asyncio.run(_schema_summary(settings))
    assert first_schema.tables >= _CONTENT_TABLES
    assert first_schema.vector_type == f"vector({EMBEDDING_DIMENSION})"
    assert "activated_at IS NOT NULL" in first_schema.indexes["uq_book_documents_active_book"]
    active_run_index = first_schema.indexes["uq_ingestion_runs_active_document"]
    assert "CREATE UNIQUE INDEX" in active_run_index
    assert "queued" in active_run_index
    assert "running" in active_run_index
    asyncio.run(_round_trip_full_content_graph(settings))

    command.downgrade(config, "base")
    assert asyncio.run(_database_is_ready(settings)) is False

    command.upgrade(config, "head")
    assert asyncio.run(_database_is_ready(settings)) is True
    rebuilt_schema = asyncio.run(_schema_summary(settings))
    assert rebuilt_schema.tables >= _CONTENT_TABLES
    assert rebuilt_schema.vector_type == f"vector({EMBEDDING_DIMENSION})"
