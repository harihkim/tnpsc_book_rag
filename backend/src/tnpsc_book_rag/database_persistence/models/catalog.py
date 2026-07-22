"""Persistent textbook catalog and immutable source-document records."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from tnpsc_book_rag.textbook_catalog.models import DocumentLanguage, DocumentState
from tnpsc_book_rag.database_persistence.metadata import Base
from tnpsc_book_rag.database_persistence.models._base import TimestampMixin, UUIDPrimaryKeyMixin
from tnpsc_book_rag.database_persistence.models._types import string_enum_type


class BookRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Conceptual textbook shared by one or more edition PDFs."""

    __tablename__ = "books"
    __table_args__ = (
        CheckConstraint("standard BETWEEN 6 AND 10", name="standard_range"),
        CheckConstraint("char_length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("char_length(btrim(subject)) > 0", name="subject_not_blank"),
        CheckConstraint("char_length(btrim(publisher)) > 0", name="publisher_not_blank"),
        Index("ix_books_catalog_filters", "standard", "subject", "language"),
        Index(
            "uq_books_catalog_identifier",
            "catalog_identifier",
            unique=True,
            postgresql_where=text("catalog_identifier IS NOT NULL"),
        ),
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    standard: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    language: Mapped[DocumentLanguage] = mapped_column(
        string_enum_type(
            DocumentLanguage,
            name="document_language_values",
            length=7,
        ),
        nullable=False,
        default=DocumentLanguage.ENGLISH,
        server_default=DocumentLanguage.ENGLISH.value,
    )
    publisher: Mapped[str] = mapped_column(String(300), nullable=False)
    catalog_identifier: Mapped[str | None] = mapped_column(String(200))


class BookDocumentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable source PDF and its extraction/activation lifecycle."""

    __tablename__ = "book_documents"
    __table_args__ = (
        UniqueConstraint("source_sha256"),
        CheckConstraint("char_length(btrim(edition)) > 0", name="edition_not_blank"),
        CheckConstraint(
            "char_length(btrim(source_filename)) > 0",
            name="source_filename_not_blank",
        ),
        CheckConstraint("media_type = 'application/pdf'", name="pdf_media_type"),
        CheckConstraint(
            "char_length(btrim(source_artifact_key)) > 0",
            name="source_artifact_key_not_blank",
        ),
        CheckConstraint(
            "docling_artifact_key IS NULL OR char_length(btrim(docling_artifact_key)) > 0",
            name="docling_artifact_key_not_blank",
        ),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="source_sha256_format",
        ),
        CheckConstraint("file_size_bytes > 0", name="file_size_positive"),
        CheckConstraint(
            "page_count IS NULL OR page_count > 0",
            name="page_count_positive",
        ),
        CheckConstraint(
            "activated_at IS NULL OR state = 'ready'",
            name="active_document_ready",
        ),
        CheckConstraint(
            "state <> 'ready' OR page_count IS NOT NULL",
            name="ready_document_has_pages",
        ),
        Index("ix_book_documents_book_state", "book_id", "state"),
        Index(
            "uq_book_documents_active_book",
            "book_id",
            unique=True,
            postgresql_where=text("activated_at IS NOT NULL"),
        ),
    )

    book_id: Mapped[UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"),
        nullable=False,
    )
    edition: Mapped[str] = mapped_column(String(200), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="application/pdf",
        server_default="application/pdf",
    )
    source_artifact_key: Mapped[str] = mapped_column(Text, nullable=False)
    docling_artifact_key: Mapped[str | None] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[DocumentState] = mapped_column(
        string_enum_type(
            DocumentState,
            name="document_state_values",
            length=10,
        ),
        nullable=False,
        default=DocumentState.UPLOADED,
        server_default=DocumentState.UPLOADED.value,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
