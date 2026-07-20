"""Persistent state for auditable and safely claimable ingestion attempts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tnpsc_book_rag.db.metadata import Base
from tnpsc_book_rag.db.models._base import TimestampMixin, UUIDPrimaryKeyMixin
from tnpsc_book_rag.db.models._types import string_enum_type
from tnpsc_book_rag.ingestion.models import IngestionStage
from tnpsc_book_rag.ingestion.status import IngestionRunStatus


class IngestionRunRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One durable ingestion attempt, including retry and failure diagnostics."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint("retry_count >= 0", name="retry_count_nonnegative"),
        CheckConstraint(
            "completed_at IS NULL OR status IN ('succeeded', 'failed')",
            name="completion_is_terminal",
        ),
        CheckConstraint(
            "started_at IS NULL OR completed_at IS NULL OR completed_at >= started_at",
            name="timestamps_ordered",
        ),
        CheckConstraint(
            "extraction_config_fingerprint IS NULL "
            "OR extraction_config_fingerprint ~ '^[0-9a-f]{64}$'",
            name="extraction_fingerprint_format",
        ),
        CheckConstraint(
            "chunker_config_fingerprint IS NULL OR chunker_config_fingerprint ~ '^[0-9a-f]{64}$'",
            name="chunker_fingerprint_format",
        ),
        Index("ix_ingestion_runs_claim", "status", "created_at"),
        Index("ix_ingestion_runs_document_created", "document_id", "created_at"),
        Index(
            "uq_ingestion_runs_active_document",
            "document_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("book_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[IngestionRunStatus] = mapped_column(
        string_enum_type(
            IngestionRunStatus,
            name="ingestion_run_status_values",
            length=9,
        ),
        nullable=False,
        default=IngestionRunStatus.QUEUED,
        server_default=IngestionRunStatus.QUEUED.value,
    )
    current_stage: Mapped[IngestionStage] = mapped_column(
        string_enum_type(
            IngestionStage,
            name="ingestion_stage_values",
            length=10,
        ),
        nullable=False,
        default=IngestionStage.QUEUED,
        server_default=IngestionStage.QUEUED.value,
    )
    worker_id: Mapped[str | None] = mapped_column(String(200))
    docling_version: Mapped[str | None] = mapped_column(String(100))
    extraction_config_fingerprint: Mapped[str | None] = mapped_column(String(64))
    chunker_version: Mapped[str | None] = mapped_column(String(100))
    chunker_config_fingerprint: Mapped[str | None] = mapped_column(String(64))
    chunker_tokenizer_identifier: Mapped[str | None] = mapped_column(String(300))
    chunker_tokenizer_revision: Mapped[str | None] = mapped_column(String(200))
    embedding_model_identifier: Mapped[str | None] = mapped_column(String(300))
    embedding_model_revision: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    warning_details: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    error_details: Mapped[dict[str, object] | None] = mapped_column(JSONB)
