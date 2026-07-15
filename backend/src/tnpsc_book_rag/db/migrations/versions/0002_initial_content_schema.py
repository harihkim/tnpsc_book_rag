"""Add the catalog, ingestion, provenance, and embedding schema.

Revision ID: 0002_initial_content_schema
Revises: 0001_enable_pgvector
Created: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision: str = "0002_initial_content_schema"
down_revision: str | Sequence[str] | None = "0001_enable_pgvector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum_type(*values: str, name: str, length: int) -> sa.Enum[str]:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=length,
    )


def upgrade() -> None:
    """Create durable textbook content and ingestion records."""
    op.create_table(
        "books",
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("standard", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column(
            "language",
            _enum_type("english", name="document_language_values", length=7),
            server_default="english",
            nullable=False,
        ),
        sa.Column("publisher", sa.String(length=300), nullable=False),
        sa.Column("catalog_identifier", sa.String(length=200), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(publisher)) > 0",
            name=op.f("ck_books_publisher_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(subject)) > 0",
            name=op.f("ck_books_subject_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(title)) > 0",
            name=op.f("ck_books_title_not_blank"),
        ),
        sa.CheckConstraint(
            "standard BETWEEN 6 AND 10",
            name=op.f("ck_books_standard_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_books")),
    )
    op.create_index(
        "ix_books_catalog_filters",
        "books",
        ["standard", "subject", "language"],
        unique=False,
    )
    op.create_index(
        "uq_books_catalog_identifier",
        "books",
        ["catalog_identifier"],
        unique=True,
        postgresql_where=sa.text("catalog_identifier IS NOT NULL"),
    )

    op.create_table(
        "book_documents",
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("edition", sa.String(length=200), nullable=False),
        sa.Column("source_filename", sa.String(length=500), nullable=False),
        sa.Column(
            "media_type",
            sa.String(length=100),
            server_default="application/pdf",
            nullable=False,
        ),
        sa.Column("source_artifact_key", sa.Text(), nullable=False),
        sa.Column("docling_artifact_key", sa.Text(), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "state",
            _enum_type(
                "uploaded",
                "queued",
                "extracting",
                "chunking",
                "embedding",
                "ready",
                "failed",
                name="document_state_values",
                length=10,
            ),
            server_default="uploaded",
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "activated_at IS NULL OR state = 'ready'",
            name=op.f("ck_book_documents_active_document_ready"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(edition)) > 0",
            name=op.f("ck_book_documents_edition_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(source_filename)) > 0",
            name=op.f("ck_book_documents_source_filename_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(source_artifact_key)) > 0",
            name=op.f("ck_book_documents_source_artifact_key_not_blank"),
        ),
        sa.CheckConstraint(
            "docling_artifact_key IS NULL OR char_length(btrim(docling_artifact_key)) > 0",
            name=op.f("ck_book_documents_docling_artifact_key_not_blank"),
        ),
        sa.CheckConstraint(
            "file_size_bytes > 0",
            name=op.f("ck_book_documents_file_size_positive"),
        ),
        sa.CheckConstraint(
            "media_type = 'application/pdf'",
            name=op.f("ck_book_documents_pdf_media_type"),
        ),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count > 0",
            name=op.f("ck_book_documents_page_count_positive"),
        ),
        sa.CheckConstraint(
            "state <> 'ready' OR page_count IS NOT NULL",
            name=op.f("ck_book_documents_ready_document_has_pages"),
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_book_documents_source_sha256_format"),
        ),
        sa.ForeignKeyConstraint(
            ["book_id"],
            ["books.id"],
            name=op.f("fk_book_documents_book_id_books"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_book_documents")),
        sa.UniqueConstraint(
            "source_sha256",
            name=op.f("uq_book_documents_source_sha256"),
        ),
    )
    op.create_index(
        "ix_book_documents_book_state",
        "book_documents",
        ["book_id", "state"],
        unique=False,
    )
    op.create_index(
        "uq_book_documents_active_book",
        "book_documents",
        ["book_id"],
        unique=True,
        postgresql_where=sa.text("activated_at IS NOT NULL"),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            _enum_type(
                "queued",
                "running",
                "succeeded",
                "failed",
                name="ingestion_run_status_values",
                length=9,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column(
            "current_stage",
            _enum_type(
                "queued",
                "extraction",
                "chunking",
                "embedding",
                "activation",
                name="ingestion_stage_values",
                length=10,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("worker_id", sa.String(length=200), nullable=True),
        sa.Column("docling_version", sa.String(length=100), nullable=True),
        sa.Column("extraction_config_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("chunker_version", sa.String(length=100), nullable=True),
        sa.Column("chunker_config_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("embedding_model_identifier", sa.String(length=300), nullable=True),
        sa.Column("embedding_model_revision", sa.String(length=200), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "warning_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "error_details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunker_config_fingerprint IS NULL OR chunker_config_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_ingestion_runs_chunker_fingerprint_format"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR status IN ('succeeded', 'failed')",
            name=op.f("ck_ingestion_runs_completion_is_terminal"),
        ),
        sa.CheckConstraint(
            "extraction_config_fingerprint IS NULL "
            "OR extraction_config_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_ingestion_runs_extraction_fingerprint_format"),
        ),
        sa.CheckConstraint(
            "retry_count >= 0",
            name=op.f("ck_ingestion_runs_retry_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR completed_at IS NULL OR completed_at >= started_at",
            name=op.f("ck_ingestion_runs_timestamps_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["book_documents.id"],
            name=op.f("fk_ingestion_runs_document_id_book_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
    )
    op.create_index(
        "ix_ingestion_runs_claim",
        "ingestion_runs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ingestion_runs_document_created",
        "ingestion_runs",
        ["document_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_ingestion_runs_active_document",
        "ingestion_runs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "pages",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("pdf_page_index", sa.Integer(), nullable=False),
        sa.Column("printed_page_label", sa.String(length=100), nullable=True),
        sa.Column("width", sa.Float(), nullable=True),
        sa.Column("height", sa.Float(), nullable=True),
        sa.Column("raw_text", sa.Text(), server_default="", nullable=False),
        sa.Column("normalized_text", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "extraction_warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "height IS NULL OR height > 0",
            name=op.f("ck_pages_height_positive"),
        ),
        sa.CheckConstraint(
            "pdf_page_index >= 0",
            name=op.f("ck_pages_pdf_page_index_nonnegative"),
        ),
        sa.CheckConstraint(
            "width IS NULL OR width > 0",
            name=op.f("ck_pages_width_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["book_documents.id"],
            name=op.f("fk_pages_document_id_book_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_pages_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pages")),
        sa.UniqueConstraint(
            "document_id",
            "pdf_page_index",
            name=op.f("uq_pages_document_id_pdf_page_index"),
        ),
    )
    op.create_index(
        "ix_pages_ingestion_run_id",
        "pages",
        ["ingestion_run_id"],
        unique=False,
    )

    op.create_table(
        "assets",
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "asset_type",
            _enum_type(
                "image",
                "diagram",
                "map",
                "photograph",
                "figure",
                "unknown",
                name="asset_type_values",
                length=10,
            ),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("artifact_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=200), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column(
            "bounding_box",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("coordinate_origin", sa.String(length=50), nullable=True),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(artifact_key)) > 0",
            name=op.f("ck_assets_artifact_key_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(mime_type)) > 0",
            name=op.f("ck_assets_mime_type_not_blank"),
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_assets_sha256_format"),
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_assets_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["pages.id"],
            name=op.f("fk_assets_page_id_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
    )
    op.create_index("ix_assets_page_id", "assets", ["page_id"], unique=False)
    op.create_index(
        "ix_assets_ingestion_run_id",
        "assets",
        ["ingestion_run_id"],
        unique=False,
    )

    op.create_table(
        "chunks",
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column("embedding_text", sa.Text(), nullable=False),
        sa.Column("chapter_title", sa.String(length=500), nullable=True),
        sa.Column(
            "section_path",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "content_type",
            _enum_type(
                "prose",
                "heading",
                "list",
                "table",
                "caption",
                "mixed",
                name="chunk_content_type_values",
                length=7,
            ),
            nullable=False,
        ),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(display_text)) > 0",
            name=op.f("ck_chunks_display_text_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(embedding_text)) > 0",
            name=op.f("ck_chunks_embedding_text_not_blank"),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_chunks_content_sha256_format"),
        ),
        sa.CheckConstraint(
            "sequence_number >= 0",
            name=op.f("ck_chunks_sequence_nonnegative"),
        ),
        sa.CheckConstraint(
            "token_count > 0",
            name=op.f("ck_chunks_token_count_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["book_documents.id"],
            name=op.f("fk_chunks_document_id_book_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_chunks_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["pages.id"],
            name=op.f("fk_chunks_page_id_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint(
            "document_id",
            "sequence_number",
            name=op.f("uq_chunks_document_id_sequence_number"),
        ),
    )
    op.create_index("ix_chunks_page_id", "chunks", ["page_id"], unique=False)
    op.create_index(
        "ix_chunks_ingestion_run_id",
        "chunks",
        ["ingestion_run_id"],
        unique=False,
    )

    op.create_table(
        "chunk_pages",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("span_order", sa.Integer(), nullable=False),
        sa.Column("character_start", sa.Integer(), nullable=True),
        sa.Column("character_end", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(character_start IS NULL AND character_end IS NULL) "
            "OR (character_start >= 0 AND character_end > character_start)",
            name=op.f("ck_chunk_pages_character_span_valid"),
        ),
        sa.CheckConstraint(
            "span_order >= 0",
            name=op.f("ck_chunk_pages_span_order_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["chunks.id"],
            name=op.f("fk_chunk_pages_chunk_id_chunks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["pages.id"],
            name=op.f("fk_chunk_pages_page_id_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunk_pages")),
        sa.UniqueConstraint(
            "chunk_id",
            "page_id",
            name=op.f("uq_chunk_pages_chunk_id_page_id"),
        ),
        sa.UniqueConstraint(
            "chunk_id",
            "span_order",
            name=op.f("uq_chunk_pages_chunk_id_span_order"),
        ),
    )
    op.create_index(
        "ix_chunk_pages_page_id",
        "chunk_pages",
        ["page_id"],
        unique=False,
    )

    op.create_table(
        "chunk_embeddings",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("model_identifier", sa.String(length=300), nullable=False),
        sa.Column("model_revision", sa.String(length=200), nullable=False),
        sa.Column("dimension", sa.SmallInteger(), server_default="384", nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("embedding", VECTOR(dim=384), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(model_identifier)) > 0",
            name=op.f("ck_chunk_embeddings_model_identifier_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(model_revision)) > 0",
            name=op.f("ck_chunk_embeddings_model_revision_not_blank"),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_chunk_embeddings_content_sha256_format"),
        ),
        sa.CheckConstraint(
            "dimension = 384",
            name=op.f("ck_chunk_embeddings_supported_dimension"),
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["chunks.id"],
            name=op.f("fk_chunk_embeddings_chunk_id_chunks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunk_embeddings")),
        sa.UniqueConstraint(
            "chunk_id",
            "model_identifier",
            "model_revision",
            name=op.f("uq_chunk_embeddings_chunk_id_model_identifier_model_revision"),
        ),
    )
    op.create_index(
        "ix_chunk_embeddings_model",
        "chunk_embeddings",
        ["model_identifier", "model_revision"],
        unique=False,
    )


def downgrade() -> None:
    """Remove derived content before catalog and ingestion parents."""
    op.drop_table("chunk_embeddings")
    op.drop_table("chunk_pages")
    op.drop_table("chunks")
    op.drop_table("assets")
    op.drop_table("pages")
    op.drop_table("ingestion_runs")
    op.drop_table("book_documents")
    op.drop_table("books")
