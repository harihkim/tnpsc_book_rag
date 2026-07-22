"""Add semantic content parents and tokenizer-aware retrieval children.

Revision ID: 0005_parent_child_content
Revises: 0004_asset_dimensions
Created: 2026-07-19
"""

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_parent_child_content"
down_revision: str | Sequence[str] | None = "0004_asset_dimensions"
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


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _parent_sha256(display_text: str) -> str:
    value = {
        "display_format": "plain_text",
        "display_text": display_text,
        "structured_content": None,
    }
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return _text_sha256(payload)


def _require_backfillable_sequences() -> None:
    oversized = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM chunks WHERE sequence_number > 999999"))
        .scalar_one()
    )
    if oversized:
        raise RuntimeError(
            "legacy chunks with sequence numbers above 999999 must be remediated before upgrade"
        )


def _backfill_checksums() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, display_text, embedding_text FROM chunks ORDER BY id")
    ).mappings()
    for row in rows:
        display_sha256 = _text_sha256(str(row["display_text"]))
        embedding_sha256 = _text_sha256(str(row["embedding_text"]))
        connection.execute(
            sa.text(
                "UPDATE chunks SET display_sha256 = :display_sha256, "
                "embedding_sha256 = :embedding_sha256 WHERE id = :chunk_id"
            ),
            {
                "chunk_id": row["id"],
                "display_sha256": display_sha256,
                "embedding_sha256": embedding_sha256,
            },
        )
        connection.execute(
            sa.text(
                "UPDATE content_units SET content_sha256 = :content_sha256 WHERE id = :unit_id"
            ),
            {
                "unit_id": row["id"],
                "content_sha256": _parent_sha256(str(row["display_text"])),
            },
        )
    connection.execute(
        sa.text(
            "UPDATE chunk_embeddings AS embedding "
            "SET content_sha256 = chunk.embedding_sha256 "
            "FROM chunks AS chunk WHERE embedding.chunk_id = chunk.id"
        )
    )


def upgrade() -> None:
    """Backfill v1 chunks into parents, then enforce the package-v2 schema."""
    _require_backfillable_sequences()
    op.add_column(
        "ingestion_runs",
        sa.Column("chunker_tokenizer_identifier", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "ingestion_runs",
        sa.Column("chunker_tokenizer_revision", sa.String(length=200), nullable=True),
    )
    op.create_table(
        "content_units",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_local_id", sa.String(length=7), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "unit_type",
            _enum_type(
                "section",
                "prose",
                "definition",
                "law",
                "solved_example",
                "activity",
                "table",
                "list",
                "caption",
                "mixed",
                name="content_unit_type_values",
                length=14,
            ),
            nullable=False,
        ),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column(
            "display_format",
            _enum_type(
                "plain_text",
                "markdown",
                name="display_format_values",
                length=10,
            ),
            nullable=False,
        ),
        sa.Column(
            "structured_content",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "section_path",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "retrieval_eligible",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "docling_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
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
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_content_units_content_sha256_format"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(display_text)) > 0",
            name=op.f("ck_content_units_display_text_not_blank"),
        ),
        sa.CheckConstraint(
            "(retrieval_eligible AND exclusion_reason IS NULL) OR "
            "(NOT retrieval_eligible AND char_length(btrim(exclusion_reason)) > 0)",
            name=op.f("ck_content_units_retrieval_eligibility_consistent"),
        ),
        sa.CheckConstraint(
            "sequence_number >= 0",
            name=op.f("ck_content_units_sequence_nonnegative"),
        ),
        sa.CheckConstraint(
            "source_local_id ~ '^U[0-9]{6}$'",
            name=op.f("ck_content_units_source_local_id_format"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["book_documents.id"],
            name=op.f("fk_content_units_document_id_book_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_content_units_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_units")),
        sa.UniqueConstraint(
            "ingestion_run_id",
            "sequence_number",
            name=op.f("uq_content_units_ingestion_run_id_sequence_number"),
        ),
        sa.UniqueConstraint(
            "ingestion_run_id",
            "source_local_id",
            name=op.f("uq_content_units_ingestion_run_id_source_local_id"),
        ),
    )
    op.create_index(
        "ix_content_units_ingestion_run_id",
        "content_units",
        ["ingestion_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_content_units_unit_type",
        "content_units",
        ["unit_type"],
        unique=False,
    )
    op.create_index(
        "ix_content_units_document_retrieval",
        "content_units",
        ["document_id", "retrieval_eligible"],
        unique=False,
    )

    op.execute(
        sa.text(
            "INSERT INTO content_units "
            "(id, document_id, ingestion_run_id, source_local_id, sequence_number, unit_type, "
            "display_text, display_format, structured_content, section_path, retrieval_eligible, "
            "exclusion_reason, content_sha256, docling_refs, provenance, created_at) "
            "SELECT id, document_id, ingestion_run_id, "
            "'U' || lpad(sequence_number::text, 6, '0'), sequence_number, 'mixed', "
            "display_text, 'plain_text', NULL, section_path, true, NULL, content_sha256, "
            "'[]'::jsonb, provenance, created_at FROM chunks"
        )
    )
    op.create_table(
        "content_unit_pages",
        sa.Column("content_unit_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("span_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "span_order >= 0",
            name=op.f("ck_content_unit_pages_span_order_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["content_unit_id"],
            ["content_units.id"],
            name=op.f("fk_content_unit_pages_content_unit_id_content_units"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["pages.id"],
            name=op.f("fk_content_unit_pages_page_id_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_unit_pages")),
        sa.UniqueConstraint(
            "content_unit_id",
            "page_id",
            name=op.f("uq_content_unit_pages_content_unit_id_page_id"),
        ),
        sa.UniqueConstraint(
            "content_unit_id",
            "span_order",
            name=op.f("uq_content_unit_pages_content_unit_id_span_order"),
        ),
    )
    op.create_index(
        "ix_content_unit_pages_page_id",
        "content_unit_pages",
        ["page_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            "INSERT INTO content_unit_pages (id, content_unit_id, page_id, span_order, created_at) "
            "SELECT id, chunk_id, page_id, span_order, created_at FROM chunk_pages"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO content_unit_pages (id, content_unit_id, page_id, span_order, created_at) "
            "SELECT chunk.id, chunk.id, chunk.page_id, 0, chunk.created_at FROM chunks AS chunk "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM chunk_pages AS page WHERE page.chunk_id = chunk.id)"
        )
    )

    op.add_column("chunks", sa.Column("content_unit_id", sa.Uuid(), nullable=True))
    op.add_column("chunks", sa.Column("source_local_id", sa.String(length=7), nullable=True))
    op.add_column(
        "chunks",
        sa.Column(
            "display_format",
            sa.String(length=10),
            server_default="plain_text",
            nullable=True,
        ),
    )
    op.add_column("chunks", sa.Column("display_sha256", sa.String(length=64), nullable=True))
    op.add_column("chunks", sa.Column("embedding_sha256", sa.String(length=64), nullable=True))
    op.add_column(
        "chunks",
        sa.Column(
            "docling_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE chunks SET content_unit_id = id, "
            "source_local_id = 'C' || lpad(sequence_number::text, 6, '0'), "
            "display_format = 'plain_text', display_sha256 = content_sha256, "
            "embedding_sha256 = content_sha256"
        )
    )
    _backfill_checksums()
    op.alter_column("chunks", "content_unit_id", nullable=False)
    op.alter_column("chunks", "source_local_id", nullable=False)
    op.alter_column(
        "chunks",
        "display_format",
        existing_type=sa.String(length=10),
        server_default=None,
        nullable=False,
    )
    op.alter_column("chunks", "display_sha256", nullable=False)
    op.alter_column("chunks", "embedding_sha256", nullable=False)
    op.create_foreign_key(
        op.f("fk_chunks_content_unit_id_content_units"),
        "chunks",
        "content_units",
        ["content_unit_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        op.f("ck_chunks_source_local_id_format"),
        "chunks",
        "source_local_id ~ '^C[0-9]{6}$'",
    )
    op.create_check_constraint(
        op.f("ck_chunks_chunk_display_format_values"),
        "chunks",
        "display_format IN ('plain_text', 'markdown')",
    )
    op.create_check_constraint(
        op.f("ck_chunks_display_sha256_format"),
        "chunks",
        "display_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        op.f("ck_chunks_embedding_sha256_format"),
        "chunks",
        "embedding_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.drop_constraint(
        op.f("uq_chunks_document_id_sequence_number"),
        "chunks",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_chunks_ingestion_run_id_sequence_number"),
        "chunks",
        ["ingestion_run_id", "sequence_number"],
    )
    op.create_unique_constraint(
        op.f("uq_chunks_ingestion_run_id_source_local_id"),
        "chunks",
        ["ingestion_run_id", "source_local_id"],
    )
    op.create_index(
        "ix_chunks_content_unit_id",
        "chunks",
        ["content_unit_id"],
        unique=False,
    )
    op.create_index(
        "ix_chunks_document_content_type",
        "chunks",
        ["document_id", "content_type"],
        unique=False,
    )
    op.drop_constraint(
        op.f("ck_chunks_content_sha256_format"),
        "chunks",
        type_="check",
    )
    op.drop_column("chunks", "content_sha256")


def _require_downgradeable_documents() -> None:
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM ("
                "SELECT document_id, sequence_number FROM chunks "
                "GROUP BY document_id, sequence_number HAVING count(*) > 1"
                ") AS duplicate_sequences"
            )
        )
        .scalar_one()
    )
    if duplicates:
        raise RuntimeError(
            "cannot downgrade while multiple ingestion runs retain the same document sequence"
        )


def downgrade() -> None:
    """Restore the v1 child-only shape when document sequences remain unique."""
    _require_downgradeable_documents()
    op.add_column("chunks", sa.Column("content_sha256", sa.String(length=64), nullable=True))
    op.execute(sa.text("UPDATE chunks SET content_sha256 = display_sha256"))
    op.execute(
        sa.text(
            "UPDATE chunk_embeddings AS embedding SET content_sha256 = chunk.display_sha256 "
            "FROM chunks AS chunk WHERE embedding.chunk_id = chunk.id"
        )
    )
    op.alter_column("chunks", "content_sha256", nullable=False)
    op.create_check_constraint(
        op.f("ck_chunks_content_sha256_format"),
        "chunks",
        "content_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.drop_index("ix_chunks_document_content_type", table_name="chunks")
    op.drop_index("ix_chunks_content_unit_id", table_name="chunks")
    op.drop_constraint(
        op.f("uq_chunks_ingestion_run_id_source_local_id"),
        "chunks",
        type_="unique",
    )
    op.drop_constraint(
        op.f("uq_chunks_ingestion_run_id_sequence_number"),
        "chunks",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_chunks_document_id_sequence_number"),
        "chunks",
        ["document_id", "sequence_number"],
    )
    op.drop_constraint(op.f("ck_chunks_embedding_sha256_format"), "chunks", type_="check")
    op.drop_constraint(op.f("ck_chunks_display_sha256_format"), "chunks", type_="check")
    op.drop_constraint(
        op.f("ck_chunks_chunk_display_format_values"),
        "chunks",
        type_="check",
    )
    op.drop_constraint(op.f("ck_chunks_source_local_id_format"), "chunks", type_="check")
    op.drop_constraint(
        op.f("fk_chunks_content_unit_id_content_units"),
        "chunks",
        type_="foreignkey",
    )
    op.drop_column("chunks", "docling_refs")
    op.drop_column("chunks", "embedding_sha256")
    op.drop_column("chunks", "display_sha256")
    op.drop_column("chunks", "display_format")
    op.drop_column("chunks", "source_local_id")
    op.drop_column("chunks", "content_unit_id")
    op.drop_index("ix_content_unit_pages_page_id", table_name="content_unit_pages")
    op.drop_table("content_unit_pages")
    op.drop_index("ix_content_units_document_retrieval", table_name="content_units")
    op.drop_index("ix_content_units_unit_type", table_name="content_units")
    op.drop_index("ix_content_units_ingestion_run_id", table_name="content_units")
    op.drop_table("content_units")
    op.drop_column("ingestion_runs", "chunker_tokenizer_revision")
    op.drop_column("ingestion_runs", "chunker_tokenizer_identifier")
