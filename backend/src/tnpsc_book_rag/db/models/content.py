"""Persistent page, asset, chunk, provenance, and embedding records."""

from uuid import UUID

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tnpsc_book_rag.catalog.models import AssetType, ChunkContentType
from tnpsc_book_rag.db.metadata import Base
from tnpsc_book_rag.db.models._base import CreatedAtMixin, UUIDPrimaryKeyMixin
from tnpsc_book_rag.db.models._types import string_enum_type

EMBEDDING_DIMENSION = 384


class PageRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Text and physical provenance for one zero-based PDF page index."""

    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("document_id", "pdf_page_index"),
        CheckConstraint("pdf_page_index >= 0", name="pdf_page_index_nonnegative"),
        CheckConstraint("width IS NULL OR width > 0", name="width_positive"),
        CheckConstraint("height IS NULL OR height > 0", name="height_positive"),
        Index("ix_pages_ingestion_run_id", "ingestion_run_id"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("book_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    pdf_page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page_label: Mapped[str | None] = mapped_column(String(100))
    width: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    normalized_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    extraction_warnings: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )


class AssetRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One extracted image-like asset linked to its source page and run."""

    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(artifact_key)) > 0",
            name="artifact_key_not_blank",
        ),
        CheckConstraint("char_length(btrim(mime_type)) > 0", name="mime_type_not_blank"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        Index("ix_assets_page_id", "page_id"),
        Index("ix_assets_ingestion_run_id", "ingestion_run_id"),
    )

    page_id: Mapped[UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=False,
    )
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_type: Mapped[AssetType] = mapped_column(
        string_enum_type(AssetType, name="asset_type_values", length=10),
        nullable=False,
        default=AssetType.UNKNOWN,
        server_default=AssetType.UNKNOWN.value,
    )
    artifact_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    caption: Mapped[str | None] = mapped_column(Text)
    bounding_box: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    coordinate_origin: Mapped[str | None] = mapped_column(String(50))
    source_reference: Mapped[str | None] = mapped_column(String(500))
    provenance: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class ChunkRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Page-first retrieval unit with deterministic document sequence order."""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "sequence_number"),
        CheckConstraint("sequence_number >= 0", name="sequence_nonnegative"),
        CheckConstraint("char_length(btrim(display_text)) > 0", name="display_text_not_blank"),
        CheckConstraint(
            "char_length(btrim(embedding_text)) > 0",
            name="embedding_text_not_blank",
        ),
        CheckConstraint("token_count > 0", name="token_count_positive"),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_sha256_format",
        ),
        Index("ix_chunks_page_id", "page_id"),
        Index("ix_chunks_ingestion_run_id", "ingestion_run_id"),
    )

    page_id: Mapped[UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("book_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_text: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_title: Mapped[str | None] = mapped_column(String(500))
    section_path: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    content_type: Mapped[ChunkContentType] = mapped_column(
        string_enum_type(
            ChunkContentType,
            name="chunk_content_type_values",
            length=7,
        ),
        nullable=False,
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class ChunkPageRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Explicit ordered page provenance for exceptional cross-page chunks."""

    __tablename__ = "chunk_pages"
    __table_args__ = (
        UniqueConstraint("chunk_id", "page_id"),
        UniqueConstraint("chunk_id", "span_order"),
        CheckConstraint("span_order >= 0", name="span_order_nonnegative"),
        CheckConstraint(
            "(character_start IS NULL AND character_end IS NULL) "
            "OR (character_start >= 0 AND character_end > character_start)",
            name="character_span_valid",
        ),
        Index("ix_chunk_pages_page_id", "page_id"),
    )

    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_id: Mapped[UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=False,
    )
    span_order: Mapped[int] = mapped_column(Integer, nullable=False)
    character_start: Mapped[int | None] = mapped_column(Integer)
    character_end: Mapped[int | None] = mapped_column(Integer)


class ChunkEmbeddingRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Versioned local embedding kept separate from extracted chunk content."""

    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "model_identifier", "model_revision"),
        CheckConstraint(
            f"dimension = {EMBEDDING_DIMENSION}",
            name="supported_dimension",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_sha256_format",
        ),
        CheckConstraint(
            "char_length(btrim(model_identifier)) > 0",
            name="model_identifier_not_blank",
        ),
        CheckConstraint(
            "char_length(btrim(model_revision)) > 0",
            name="model_revision_not_blank",
        ),
        Index(
            "ix_chunk_embeddings_model",
            "model_identifier",
            "model_revision",
        ),
    )

    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_identifier: Mapped[str] = mapped_column(String(300), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(200), nullable=False)
    dimension: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=EMBEDDING_DIMENSION,
        server_default=str(EMBEDDING_DIMENSION),
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(EMBEDDING_DIMENSION), nullable=False)
