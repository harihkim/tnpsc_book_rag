"""Transport-neutral read models for ingestion and extraction inspection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from tnpsc_book_rag.ingestion_pipeline.entities import IngestionRun
from tnpsc_book_rag.ingestion_pipeline.models import IngestionStage
from tnpsc_book_rag.ingestion_pipeline.status import IngestionRunStatus
from tnpsc_book_rag.textbook_catalog.entities import BookDocument
from tnpsc_book_rag.textbook_catalog.models import AssetType, ChunkContentType, DocumentState


@dataclass(frozen=True, slots=True)
class IngestionIssue:
    """Sanitized warning or error safe for administrative API responses."""

    code: str
    message: str
    stage: IngestionStage | None
    pdf_page_index: int | None


@dataclass(frozen=True, slots=True)
class BookReference:
    """Minimal catalog identity included with a global ingestion operation."""

    id: UUID
    title: str
    standard: int
    subject: str


@dataclass(frozen=True, slots=True)
class DocumentReference:
    """Minimal source-document identity included with ingestion operations."""

    id: UUID
    edition: str
    source_filename: str
    state: DocumentState


@dataclass(frozen=True, slots=True)
class IngestionOperation:
    """One global operations-table row."""

    ingestion_run: IngestionRun
    document: DocumentReference
    book: BookReference


@dataclass(frozen=True, slots=True)
class DocumentInspection:
    """One public document and its newest ingestion attempt."""

    document: BookDocument
    latest_ingestion_run: IngestionRun | None


@dataclass(frozen=True, slots=True)
class RunListFilters:
    """Normalized filters for the global ingestion operations view."""

    statuses: tuple[IngestionRunStatus, ...] = ()
    stages: tuple[IngestionStage, ...] = ()
    book_id: UUID | None = None
    document_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RunOrderKey:
    """Newest-first stable ingestion ordering position."""

    created_at: datetime
    id: UUID


@dataclass(frozen=True, slots=True)
class PageOrderKey:
    """PDF-order stable page position."""

    pdf_page_index: int
    id: UUID


@dataclass(frozen=True, slots=True)
class ChunkOrderKey:
    """Document-order stable retrieval-child position."""

    sequence_number: int
    id: UUID


@dataclass(frozen=True, slots=True)
class PageSummary:
    """Bounded page metadata for document inspection lists."""

    id: UUID
    document_id: UUID
    pdf_page_index: int
    printed_page_label: str | None
    width: float | None
    height: float | None
    warning_count: int
    created_at: datetime

    @property
    def order_key(self) -> PageOrderKey:
        return PageOrderKey(self.pdf_page_index, self.id)


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Canonical PDF-page rectangle independent of Docling's serialized key names."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float
    coordinate_origin: str


@dataclass(frozen=True, slots=True)
class AssetInspection:
    """Public asset metadata without its private artifact-storage key."""

    id: UUID
    page_id: UUID
    asset_type: AssetType
    caption: str | None
    alt_text: str | None
    alt_text_source: Literal["caption", "manual", "unavailable", "not_applicable"]
    is_decorative: bool
    pixel_width: int | None
    pixel_height: int | None
    thumbnail_pixel_width: int | None
    thumbnail_pixel_height: int | None
    mime_type: str
    sha256: str
    bounding_box: BoundingBox | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChunkSummary:
    """Human-facing retrieval child; embedding text and checksums stay private."""

    id: UUID
    page_id: UUID
    document_id: UUID
    sequence_number: int
    display_text: str
    chapter_title: str | None
    section_path: tuple[str, ...]
    content_type: ChunkContentType
    token_count: int
    created_at: datetime

    @property
    def order_key(self) -> ChunkOrderKey:
        return ChunkOrderKey(self.sequence_number, self.id)


@dataclass(frozen=True, slots=True)
class PageDetail:
    """Complete administrative page view with directly associated assets and children."""

    summary: PageSummary
    raw_text: str
    normalized_text: str
    warnings: tuple[IngestionIssue, ...]
    chunks: tuple[ChunkSummary, ...]
    assets: tuple[AssetInspection, ...]


@dataclass(frozen=True, slots=True)
class InspectionWindow[T]:
    """Repository keyset window plus adjacent-page availability."""

    items: tuple[T, ...]
    has_previous: bool
    has_next: bool


@dataclass(frozen=True, slots=True)
class InspectionPage[T]:
    """Application page with opaque cursors and optional exact count."""

    items: tuple[T, ...]
    previous_cursor: str | None
    next_cursor: str | None
    total_items: int | None
