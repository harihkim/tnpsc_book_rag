"""Unit-level checks for the package-owned SQLAlchemy schema contract."""

from typing import cast

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

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
    schema_metadata,
)
from tnpsc_book_rag.ingestion_pipeline.models import IngestionStage
from tnpsc_book_rag.ingestion_pipeline.status import IngestionRunStatus
from tnpsc_book_rag.textbook_catalog.models import (
    AssetType,
    ChunkContentType,
    DocumentLanguage,
    DocumentState,
)
from tnpsc_extraction.models import ContentUnitType, DisplayFormat

_EXPECTED_TABLES = {
    "assets",
    "book_documents",
    "books",
    "chunk_embeddings",
    "chunk_pages",
    "chunks",
    "content_unit_pages",
    "content_units",
    "idempotency_records",
    "ingestion_runs",
    "pages",
}


def test_schema_registers_every_initial_content_table() -> None:
    """Alembic autogeneration sees every record imported by the DB package."""
    assert set(schema_metadata.tables) == _EXPECTED_TABLES
    for table in schema_metadata.sorted_tables:
        assert table.primary_key.name is not None
        assert all(constraint.name is not None for constraint in table.constraints)


def test_database_enums_use_domain_values_instead_of_member_names() -> None:
    """Persistence consumes the committed lifecycle values without redefining them."""
    enum_columns = (
        (BookRecord.__table__.c.language, DocumentLanguage),
        (BookDocumentRecord.__table__.c.state, DocumentState),
        (IngestionRunRecord.__table__.c.status, IngestionRunStatus),
        (IngestionRunRecord.__table__.c.current_stage, IngestionStage),
        (AssetRecord.__table__.c.asset_type, AssetType),
        (ContentUnitRecord.__table__.c.unit_type, ContentUnitType),
        (ContentUnitRecord.__table__.c.display_format, DisplayFormat),
        (ChunkRecord.__table__.c.content_type, ChunkContentType),
        (ChunkRecord.__table__.c.display_format, DisplayFormat),
    )

    for column, enum_class in enum_columns:
        assert isinstance(column.type, SqlEnum)
        assert column.type.enums == [member.value for member in enum_class]


def test_embedding_column_has_fixed_dimension_without_ann_index() -> None:
    """The MVP stores BGE-small vectors but defers HNSW until measurements justify it."""
    embedding_table = cast(Table, ChunkEmbeddingRecord.__table__)
    ddl = str(
        CreateTable(embedding_table).compile(
            dialect=postgresql.dialect(),
        )
    ).upper()

    assert EMBEDDING_DIMENSION == 384
    assert "VECTOR(384)" in ddl
    assert all(
        "hnsw" not in str(index.dialect_options["postgresql"].get("using", "")).lower()
        for index in embedding_table.indexes
    )


def test_schema_enforces_single_active_document_and_active_run() -> None:
    """Partial unique indexes prevent concurrent catalog and worker activation races."""
    document_table = cast(Table, BookDocumentRecord.__table__)
    run_table = cast(Table, IngestionRunRecord.__table__)
    document_indexes = {
        str(index.name): index for index in document_table.indexes if index.name is not None
    }
    run_indexes = {str(index.name): index for index in run_table.indexes if index.name is not None}

    active_document = document_indexes["uq_book_documents_active_book"]
    active_run = run_indexes["uq_ingestion_runs_active_document"]

    assert active_document.unique
    assert "activated_at IS NOT NULL" in str(active_document.dialect_options["postgresql"]["where"])
    assert active_run.unique
    assert "status IN ('queued', 'running')" in str(
        active_run.dialect_options["postgresql"]["where"]
    )


def test_derived_records_are_auditable_and_cascade_with_their_source() -> None:
    """Derived rows retain creation time and cannot outlive source provenance."""
    records = (
        PageRecord,
        AssetRecord,
        ContentUnitRecord,
        ContentUnitPageRecord,
        ChunkRecord,
        ChunkPageRecord,
        ChunkEmbeddingRecord,
    )

    for record in records:
        assert "created_at" in record.__table__.c
        assert all(
            foreign_key.ondelete == "CASCADE" for foreign_key in record.__table__.foreign_keys
        )


def test_parent_child_content_is_run_scoped_and_checksum_explicit() -> None:
    """The v2 schema preserves semantic expansion and exact embedding identity."""
    content_unit_table = cast(Table, ContentUnitRecord.__table__)
    chunk_table = cast(Table, ChunkRecord.__table__)
    run_table = cast(Table, IngestionRunRecord.__table__)
    unit_constraints = {str(constraint.name) for constraint in content_unit_table.constraints}
    chunk_constraints = {str(constraint.name) for constraint in chunk_table.constraints}
    chunk_indexes = {str(index.name) for index in chunk_table.indexes}

    assert chunk_table.c.content_unit_id.nullable is False
    assert "content_sha256" not in chunk_table.c
    assert {"display_sha256", "embedding_sha256", "docling_refs"} <= set(chunk_table.c.keys())
    assert "uq_content_units_ingestion_run_id_sequence_number" in unit_constraints
    assert "uq_chunks_ingestion_run_id_sequence_number" in chunk_constraints
    assert "uq_chunks_document_id_sequence_number" not in chunk_constraints
    assert "ix_chunks_content_unit_id" in chunk_indexes
    assert "ix_chunks_document_content_type" in chunk_indexes
    assert {
        "chunker_tokenizer_identifier",
        "chunker_tokenizer_revision",
    } <= set(run_table.c.keys())


def test_idempotency_records_have_expiry_lookup_and_success_constraints() -> None:
    """Durable mutation replays are bounded, validated success snapshots."""
    table = cast(Table, IdempotencyRecord.__table__)
    constraint_names = {str(constraint.name) for constraint in table.constraints}
    index_names = {str(index.name) for index in table.indexes}

    assert table.primary_key.columns.keys() == ["key"]
    assert "ck_idempotency_records_key_format" in constraint_names
    assert "ck_idempotency_records_request_sha256_format" in constraint_names
    assert "ck_idempotency_records_response_status_success" in constraint_names
    assert "ix_idempotency_records_expires_at" in index_names
