"""Application-facing catalog repository contract."""

from typing import Protocol
from uuid import UUID

from tnpsc_book_rag.catalog.entities import Book, BookDocument, NewBook, NewBookDocument


class CatalogRepository(Protocol):
    """Persist and load catalog roots without owning the surrounding transaction."""

    async def add_book(self, new_book: NewBook) -> Book:
        """Register and return one conceptual textbook."""
        ...

    async def get_book(self, book_id: UUID) -> Book | None:
        """Return one textbook or ``None`` when it is absent."""
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
