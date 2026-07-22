"""Persistent replay records for externally visible mutation operations."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tnpsc_book_rag.database_persistence.metadata import Base
from tnpsc_book_rag.database_persistence.models._base import TimestampMixin


class IdempotencyRecord(TimestampMixin, Base):
    """One globally unique client key and its completed public response snapshot."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        CheckConstraint(
            "key ~ '^[A-Za-z0-9._:-]{8,128}$'",
            name="key_format",
        ),
        CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'",
            name="request_sha256_format",
        ),
        CheckConstraint(
            "response_status BETWEEN 200 AND 299",
            name="response_status_success",
        ),
        CheckConstraint(
            "char_length(btrim(operation)) > 0",
            name="operation_not_blank",
        ),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    response_headers: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
