"""Transport-neutral read models for browsing the textbook catalog."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tnpsc_book_rag.textbook_catalog.entities import BookDocument
from tnpsc_book_rag.textbook_catalog.models import CatalogStatus, DocumentLanguage, DocumentState


@dataclass(frozen=True, slots=True)
class BookOrderKey:
    """Stable, case-insensitive ordering position for keyset pagination."""

    standard: int
    subject: str
    title: str
    id: UUID


@dataclass(frozen=True, slots=True)
class BookListFilters:
    """Normalized filters accepted by the catalog listing operation."""

    standards: tuple[int, ...] = ()
    subjects: tuple[str, ...] = ()
    query: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogBook:
    """Public book fields with document-derived catalog availability."""

    id: UUID
    title: str
    standard: int
    subject: str
    language: DocumentLanguage
    publisher: str
    catalog_identifier: str | None
    catalog_status: CatalogStatus
    document_count: int
    active_document_id: UUID | None
    latest_document_id: UUID | None
    latest_document_state: DocumentState | None
    created_at: datetime
    updated_at: datetime

    @property
    def order_key(self) -> BookOrderKey:
        """Return the normalized key used by SQL and opaque cursors."""
        return BookOrderKey(
            standard=self.standard,
            subject=self.subject.casefold(),
            title=self.title.casefold(),
            id=self.id,
        )


@dataclass(frozen=True, slots=True)
class CatalogBookDetail:
    """One public book projection and all its registered editions."""

    book: CatalogBook
    documents: tuple[BookDocument, ...]


@dataclass(frozen=True, slots=True)
class CatalogBookOption:
    """Ready book option used to construct retrieval filters."""

    id: UUID
    title: str
    standard: int
    subject: str


@dataclass(frozen=True, slots=True)
class CatalogFilterOptions:
    """Filter values derived only from active ready English documents."""

    standards: tuple[int, ...]
    subjects: tuple[str, ...]
    books: tuple[CatalogBookOption, ...]


@dataclass(frozen=True, slots=True)
class BookWindow:
    """One repository keyset window and its adjacent-page availability."""

    items: tuple[CatalogBook, ...]
    has_previous: bool
    has_next: bool


@dataclass(frozen=True, slots=True)
class CatalogLibraryItem:
    """One PDF document source joined with its parent textbook catalog metadata."""

    document_id: UUID
    book_id: UUID
    title: str
    standard: int
    subject: str
    edition: str
    publisher: str
    source_filename: str
    file_size_bytes: int
    state: DocumentState
    page_count: int | None
    uploaded_at: datetime
    active: bool

