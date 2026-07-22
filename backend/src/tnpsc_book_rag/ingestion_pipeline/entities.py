"""Immutable ingestion values returned across application boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from tnpsc_book_rag.ingestion_pipeline.models import IngestionStage
from tnpsc_book_rag.ingestion_pipeline.status import IngestionRunStatus

if TYPE_CHECKING:
    from tnpsc_book_rag.textbook_catalog.entities import Book, BookDocument


@dataclass(frozen=True, slots=True)
class IngestionRun:
    """Public, sanitized state for one durable ingestion attempt."""

    id: UUID
    document_id: UUID
    status: IngestionRunStatus
    current_stage: IngestionStage
    retry_count: int
    started_at: datetime | None
    completed_at: datetime | None
    warnings: tuple[dict[str, object], ...]
    error: dict[str, object] | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionWorkItem:
    """A queued source document claimed by exactly one worker transaction."""

    book: Book
    document: BookDocument
    ingestion_run: IngestionRun
