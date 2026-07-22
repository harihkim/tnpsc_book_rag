"""Application-facing catalog repository contract."""

from typing import Protocol
from uuid import UUID

from tnpsc_book_rag.textbook_catalog.entities import Book, BookDocument, NewBook, NewBookDocument
from tnpsc_book_rag.textbook_catalog.mutations import IdempotencySnapshot, QueuedDocument
from tnpsc_book_rag.textbook_catalog.read_models import (
    BookListFilters,
    BookOrderKey,
    BookWindow,
    CatalogBookDetail,
    CatalogBookOption,
    CatalogLibraryItem,
)


class CatalogRepository(Protocol):
    """Persist and load catalog roots without owning the surrounding transaction."""

    async def add_book(self, new_book: NewBook) -> Book:
        """Register and return one conceptual textbook."""
        ...

    async def get_book(self, book_id: UUID) -> Book | None:
        """Return one textbook or ``None`` when it is absent."""
        ...

    async def get_book_by_catalog_identifier(self, catalog_identifier: str) -> Book | None:
        """Return the book using a globally unique catalog identifier, when present."""
        ...

    async def add_document(self, new_document: NewBookDocument) -> BookDocument:
        """Register immutable source metadata for one PDF edition."""
        ...

    async def get_document(self, document_id: UUID) -> BookDocument | None:
        """Return one document or ``None`` when it is absent."""
        ...

    async def get_document_by_checksum(self, source_sha256: str) -> BookDocument | None:
        """Return the globally registered source with a checksum, when present."""
        ...

    async def list_documents(self, book_id: UUID) -> tuple[BookDocument, ...]:
        """Return a book's active edition first, followed by newest editions."""
        ...

    async def get_catalog_book(self, book_id: UUID) -> CatalogBookDetail | None:
        """Return a public book projection and its documents when it exists."""
        ...

    async def list_catalog_books(
        self,
        filters: BookListFilters,
        *,
        limit: int,
        after: BookOrderKey | None = None,
        before: BookOrderKey | None = None,
    ) -> BookWindow:
        """Return one stable keyset window of public book projections."""
        ...

    async def count_catalog_books(self, filters: BookListFilters) -> int:
        """Return an exact count for the supplied catalog filters."""
        ...

    async def list_ready_book_options(self) -> tuple[CatalogBookOption, ...]:
        """Return English books with an active ready edition in catalog order."""
        ...

    async def get_library(self) -> tuple[CatalogLibraryItem, ...]:
        """Return all PDF source documents joined with textbook catalog metadata."""
        ...

    async def lock_idempotency_key(self, key: str) -> None:
        """Serialize mutations using the same client key for this transaction."""
        ...

    async def get_idempotency_snapshot(self, key: str) -> IdempotencySnapshot | None:
        """Return a completed replay snapshot for a client key, when present."""
        ...

    async def add_idempotency_snapshot(self, snapshot: IdempotencySnapshot) -> None:
        """Persist the completed public response inside the mutation transaction."""
        ...

    async def add_queued_document(self, new_document: NewBookDocument) -> QueuedDocument:
        """Atomically register one queued PDF and its initial ingestion run."""
        ...
