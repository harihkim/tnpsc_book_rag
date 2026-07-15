"""SQLAlchemy adapter for the application-facing catalog repository."""

from typing import override
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tnpsc_book_rag.catalog.entities import Book, BookDocument, NewBook, NewBookDocument
from tnpsc_book_rag.catalog.ports import CatalogRepository
from tnpsc_book_rag.db.models import BookDocumentRecord, BookRecord


def _book_from_record(record: BookRecord) -> Book:
    return Book(
        id=record.id,
        title=record.title,
        standard=record.standard,
        subject=record.subject,
        language=record.language,
        publisher=record.publisher,
        catalog_identifier=record.catalog_identifier,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _document_from_record(record: BookDocumentRecord) -> BookDocument:
    return BookDocument(
        id=record.id,
        book_id=record.book_id,
        edition=record.edition,
        source_filename=record.source_filename,
        media_type=record.media_type,
        source_artifact_key=record.source_artifact_key,
        docling_artifact_key=record.docling_artifact_key,
        source_sha256=record.source_sha256,
        file_size_bytes=record.file_size_bytes,
        page_count=record.page_count,
        state=record.state,
        activated_at=record.activated_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class SqlAlchemyCatalogRepository(CatalogRepository):
    """Catalog persistence scoped to one caller-owned async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add_book(self, new_book: NewBook) -> Book:
        """Add a book and flush it without committing the caller's transaction."""
        record = BookRecord(
            title=new_book.title,
            standard=new_book.standard,
            subject=new_book.subject,
            language=new_book.language,
            publisher=new_book.publisher,
            catalog_identifier=new_book.catalog_identifier,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        return _book_from_record(record)

    @override
    async def get_book(self, book_id: UUID) -> Book | None:
        """Load a book by primary key."""
        record = await self._session.get(BookRecord, book_id)
        return None if record is None else _book_from_record(record)

    @override
    async def add_document(self, new_document: NewBookDocument) -> BookDocument:
        """Add immutable PDF metadata and flush without committing."""
        record = BookDocumentRecord(
            book_id=new_document.book_id,
            edition=new_document.edition,
            source_filename=new_document.source_filename,
            media_type=new_document.media_type,
            source_artifact_key=new_document.source_artifact_key,
            source_sha256=new_document.source_sha256,
            file_size_bytes=new_document.file_size_bytes,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        return _document_from_record(record)

    @override
    async def get_document(self, document_id: UUID) -> BookDocument | None:
        """Load one document by primary key."""
        record = await self._session.get(BookDocumentRecord, document_id)
        return None if record is None else _document_from_record(record)

    @override
    async def get_document_by_checksum(self, source_sha256: str) -> BookDocument | None:
        """Load the globally unique PDF registered with a source checksum."""
        statement = select(BookDocumentRecord).where(
            BookDocumentRecord.source_sha256 == source_sha256
        )
        record = await self._session.scalar(statement)
        return None if record is None else _document_from_record(record)

    @override
    async def list_documents(self, book_id: UUID) -> tuple[BookDocument, ...]:
        """Load active then newest documents using the public catalog ordering."""
        statement = (
            select(BookDocumentRecord)
            .where(BookDocumentRecord.book_id == book_id)
            .order_by(
                BookDocumentRecord.activated_at.desc().nulls_last(),
                BookDocumentRecord.created_at.desc(),
                BookDocumentRecord.id.desc(),
            )
        )
        records = await self._session.scalars(statement)
        return tuple(_document_from_record(record) for record in records)
