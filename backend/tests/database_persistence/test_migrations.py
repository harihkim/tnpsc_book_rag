"""Real-PostgreSQL verification for migration repeatability and readiness."""

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from tnpsc_book_rag.textbook_catalog.models import AssetType, ChunkContentType
from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.database_persistence import (
    EMBEDDING_DIMENSION,
    AssetRecord,
    BookDocumentRecord,
    BookRecord,
    ChunkEmbeddingRecord,
    ChunkPageRecord,
    ChunkRecord,
    ContentUnitPageRecord,
    ContentUnitRecord,
    IdempotencyRecord,
    IngestionRunRecord,
    PageRecord,
    create_database,
)
from tnpsc_extraction.models import ContentUnitType, DisplayFormat

_BACKEND_ROOT = Path(__file__).parents[2]
_CONTENT_TABLES = {
    "assets",
    "book_documents",
    "books",
    "chunk_embeddings",
    "chunk_pages",
    "chunks",
    "content_unit_pages",
    "content_units",
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
            parent_payload = json.dumps(
                {
                    "display_format": "plain_text",
                    "display_text": "Matter occupies space.",
                    "structured_content": None,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            content_unit = ContentUnitRecord(
                document_id=document.id,
                ingestion_run_id=ingestion_run.id,
                source_local_id="U000000",
                sequence_number=0,
                unit_type=ContentUnitType.DEFINITION,
                display_text="Matter occupies space.",
                display_format=DisplayFormat.PLAIN_TEXT,
                structured_content=None,
                section_path=["Matter"],
                retrieval_eligible=True,
                exclusion_reason=None,
                content_sha256=hashlib.sha256(parent_payload.encode()).hexdigest(),
                docling_refs=["#/texts/0"],
                provenance={"fixture": True},
            )
            session.add_all((asset, content_unit))
            await session.flush()

            display_sha256 = hashlib.sha256(b"Matter occupies space.").hexdigest()
            embedding_sha256 = hashlib.sha256(b"Science: Matter occupies space.").hexdigest()
            chunk = ChunkRecord(
                content_unit_id=content_unit.id,
                page_id=page.id,
                document_id=document.id,
                ingestion_run_id=ingestion_run.id,
                source_local_id="C000000",
                sequence_number=0,
                display_text="Matter occupies space.",
                display_format=DisplayFormat.PLAIN_TEXT,
                embedding_text="Science: Matter occupies space.",
                content_type=ChunkContentType.PROSE,
                token_count=4,
                display_sha256=display_sha256,
                embedding_sha256=embedding_sha256,
                docling_refs=["#/texts/0"],
            )
            session.add(chunk)
            await session.flush()

            content_unit_page = ContentUnitPageRecord(
                content_unit_id=content_unit.id,
                page_id=page.id,
                span_order=0,
            )
            chunk_page = ChunkPageRecord(
                chunk_id=chunk.id,
                page_id=page.id,
                span_order=0,
            )
            embedding = ChunkEmbeddingRecord(
                chunk_id=chunk.id,
                model_identifier="BAAI/bge-small-en-v1.5",
                model_revision="fixture-revision",
                content_sha256=chunk.embedding_sha256,
                embedding=[0.0] * EMBEDDING_DIMENSION,
            )
            session.add_all((content_unit_page, chunk_page, embedding))
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


async def _insert_v1_content_graph(settings: Settings) -> tuple[UUID, str, str]:
    """Insert one valid child-only graph while the database is at revision 0004."""
    database = create_database(settings)
    assert database is not None
    book_id = uuid4()
    document_id = uuid4()
    run_id = uuid4()
    page_id = uuid4()
    chunk_id = uuid4()
    chunk_page_id = uuid4()
    embedding_id = uuid4()
    display_text = "Matter occupies space."
    embedding_text = "Science | Matter occupies space."
    display_sha256 = hashlib.sha256(display_text.encode()).hexdigest()
    try:
        async with database.transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO books (id, title, standard, subject, publisher) "
                    "VALUES (:id, 'Migration v1 fixture', 6, 'Science', 'Government of Tamil Nadu')"
                ),
                {"id": book_id},
            )
            await session.execute(
                text(
                    "INSERT INTO book_documents "
                    "(id, book_id, edition, source_filename, source_artifact_key, source_sha256, "
                    "file_size_bytes) VALUES "
                    "(:id, :book_id, 'Term I', 'science.pdf', 'sources/science.pdf', :sha256, 1024)"
                ),
                {"id": document_id, "book_id": book_id, "sha256": "1" * 64},
            )
            await session.execute(
                text("INSERT INTO ingestion_runs (id, document_id) VALUES (:id, :document_id)"),
                {"id": run_id, "document_id": document_id},
            )
            await session.execute(
                text(
                    "INSERT INTO pages "
                    "(id, document_id, ingestion_run_id, pdf_page_index, raw_text, "
                    "normalized_text) "
                    "VALUES (:id, :document_id, :run_id, 0, :display_text, :display_text)"
                ),
                {
                    "id": page_id,
                    "document_id": document_id,
                    "run_id": run_id,
                    "display_text": display_text,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO chunks "
                    "(id, page_id, document_id, ingestion_run_id, sequence_number, display_text, "
                    "embedding_text, section_path, content_type, token_count, content_sha256, "
                    "provenance) VALUES "
                    "(:id, :page_id, :document_id, :run_id, 0, :display_text, :embedding_text, "
                    "'[]'::jsonb, 'prose', 5, :content_sha256, '{}'::jsonb)"
                ),
                {
                    "id": chunk_id,
                    "page_id": page_id,
                    "document_id": document_id,
                    "run_id": run_id,
                    "display_text": display_text,
                    "embedding_text": embedding_text,
                    "content_sha256": display_sha256,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO chunk_pages (id, chunk_id, page_id, span_order) "
                    "VALUES (:id, :chunk_id, :page_id, 0)"
                ),
                {"id": chunk_page_id, "chunk_id": chunk_id, "page_id": page_id},
            )
            await session.execute(
                text(
                    "INSERT INTO chunk_embeddings "
                    "(id, chunk_id, model_identifier, model_revision, dimension, content_sha256, "
                    "embedding) VALUES (:id, :chunk_id, 'fixture-model', 'v1', 384, "
                    ":content_sha256, array_fill(0::real, ARRAY[384])::vector)"
                ),
                {
                    "id": embedding_id,
                    "chunk_id": chunk_id,
                    "content_sha256": display_sha256,
                },
            )
    finally:
        await database.close()
    return chunk_id, display_text, embedding_text


async def _assert_v1_graph_backfilled(
    settings: Settings,
    fixture: tuple[UUID, str, str],
) -> None:
    chunk_id, display_text, embedding_text = fixture
    database = create_database(settings)
    assert database is not None
    parent_value = {
        "display_format": "plain_text",
        "display_text": display_text,
        "structured_content": None,
    }
    expected_parent_sha256 = hashlib.sha256(
        json.dumps(
            parent_value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    try:
        async with database.engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT unit.id AS unit_id, unit.source_local_id AS unit_local_id, "
                            "unit.unit_type, unit.content_sha256, chunk.content_unit_id, "
                            "chunk.source_local_id AS chunk_local_id, chunk.display_sha256, "
                            "chunk.embedding_sha256, embedding.content_sha256 AS embedded_sha256 "
                            "FROM content_units AS unit JOIN chunks AS chunk "
                            "ON chunk.content_unit_id = unit.id JOIN chunk_embeddings AS embedding "
                            "ON embedding.chunk_id = chunk.id WHERE chunk.id = :chunk_id"
                        ),
                        {"chunk_id": chunk_id},
                    )
                )
                .mappings()
                .one()
            )
            parent_page_count = await connection.scalar(
                text("SELECT count(*) FROM content_unit_pages WHERE content_unit_id = :unit_id"),
                {"unit_id": chunk_id},
            )
    finally:
        await database.close()

    expected_display_sha256 = hashlib.sha256(display_text.encode()).hexdigest()
    expected_embedding_sha256 = hashlib.sha256(embedding_text.encode()).hexdigest()
    assert row["unit_id"] == chunk_id
    assert row["content_unit_id"] == chunk_id
    assert row["unit_local_id"] == "U000000"
    assert row["chunk_local_id"] == "C000000"
    assert row["unit_type"] == "mixed"
    assert row["content_sha256"] == expected_parent_sha256
    assert row["display_sha256"] == expected_display_sha256
    assert row["embedding_sha256"] == expected_embedding_sha256
    assert row["embedded_sha256"] == expected_embedding_sha256
    assert parent_page_count == 1


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


@pytest.mark.postgres
def test_parent_child_migration_backfills_v1_content_without_reembedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing children become mixed parents and embeddings follow exact embedding text."""
    database_url = _test_database_url()
    monkeypatch.setenv("TNPSC_DATABASE_URL", database_url)
    settings = Settings.model_validate({"database_url": database_url})
    config = _alembic_config()

    command.downgrade(config, "base")
    command.upgrade(config, "0004_asset_dimensions")
    fixture = asyncio.run(_insert_v1_content_graph(settings))
    command.upgrade(config, "head")
    asyncio.run(_assert_v1_graph_backfilled(settings, fixture))

    command.downgrade(config, "0004_asset_dimensions")
    command.upgrade(config, "head")
    asyncio.run(_assert_v1_graph_backfilled(settings, fixture))
