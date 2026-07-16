"""SQLAlchemy adapter for the application-facing catalog repository."""

from collections import defaultdict
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import override
from uuid import UUID

from sqlalchemy import Select, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from tnpsc_book_rag.catalog.entities import Book, BookDocument, NewBook, NewBookDocument
from tnpsc_book_rag.catalog.models import CatalogStatus, DocumentLanguage, DocumentState
from tnpsc_book_rag.catalog.mutations import IdempotencySnapshot, QueuedDocument
from tnpsc_book_rag.catalog.ports import CatalogRepository
from tnpsc_book_rag.catalog.read_models import (
    BookListFilters,
    BookOrderKey,
    BookWindow,
    CatalogBook,
    CatalogBookDetail,
    CatalogBookOption,
)
from tnpsc_book_rag.db.database import Database
from tnpsc_book_rag.db.models import (
    BookDocumentRecord,
    BookRecord,
    IdempotencyRecord,
    IngestionRunRecord,
)
from tnpsc_book_rag.ingestion.entities import IngestionRun


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


def _ingestion_run_from_record(record: IngestionRunRecord) -> IngestionRun:
    return IngestionRun(
        id=record.id,
        document_id=record.document_id,
        status=record.status,
        current_stage=record.current_stage,
        retry_count=record.retry_count,
        started_at=record.started_at,
        completed_at=record.completed_at,
        warnings=tuple(record.warning_details),
        error=record.error_details,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _idempotency_from_record(record: IdempotencyRecord) -> IdempotencySnapshot:
    return IdempotencySnapshot(
        key=record.key,
        operation=record.operation,
        request_sha256=record.request_sha256,
        response_status=record.response_status,
        response_body=record.response_body,
        response_headers=record.response_headers,
        expires_at=record.expires_at,
    )


def _catalog_book(record: BookRecord, documents: Sequence[BookDocument]) -> CatalogBook:
    latest = max(
        documents,
        key=lambda document: (document.created_at, document.id.int),
        default=None,
    )
    active = next((document for document in documents if document.activated_at is not None), None)
    if active is not None:
        catalog_status = CatalogStatus.READY
    elif latest is None:
        catalog_status = CatalogStatus.EMPTY
    elif latest.state is DocumentState.FAILED:
        catalog_status = CatalogStatus.FAILED
    else:
        catalog_status = CatalogStatus.PROCESSING
    return CatalogBook(
        id=record.id,
        title=record.title,
        standard=record.standard,
        subject=record.subject,
        language=record.language,
        publisher=record.publisher,
        catalog_identifier=record.catalog_identifier,
        catalog_status=catalog_status,
        document_count=len(documents),
        active_document_id=None if active is None else active.id,
        latest_document_id=None if latest is None else latest.id,
        latest_document_state=None if latest is None else latest.state,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _book_filter_conditions(filters: BookListFilters) -> tuple[ColumnElement[bool], ...]:
    conditions: list[ColumnElement[bool]] = []
    if filters.standards:
        conditions.append(BookRecord.standard.in_(filters.standards))
    if filters.subjects:
        conditions.append(
            func.lower(BookRecord.subject).in_(
                tuple(subject.lower() for subject in filters.subjects)
            )
        )
    if filters.query is not None:
        conditions.append(
            or_(
                BookRecord.title.icontains(filters.query, autoescape=True),
                BookRecord.subject.icontains(filters.query, autoescape=True),
            )
        )
    return tuple(conditions)


_BOOK_ORDER_COLUMNS = (
    BookRecord.standard,
    func.lower(BookRecord.subject),
    func.lower(BookRecord.title),
    BookRecord.id,
)


def _order_values(key: BookOrderKey) -> tuple[int, str, str, UUID]:
    return key.standard, key.subject, key.title, key.id


@asynccontextmanager
async def catalog_transaction(database: Database) -> AsyncGenerator[CatalogRepository]:
    """Adapt the database transaction boundary to the catalog repository port."""
    async with database.transaction() as session:
        yield SqlAlchemyCatalogRepository(session)


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
    async def get_book_by_catalog_identifier(self, catalog_identifier: str) -> Book | None:
        """Load a book using its optional globally unique catalog identifier."""
        statement = select(BookRecord).where(BookRecord.catalog_identifier == catalog_identifier)
        record = await self._session.scalar(statement)
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

    async def _catalog_books_from_records(
        self, records: Sequence[BookRecord]
    ) -> tuple[CatalogBook, ...]:
        if not records:
            return ()
        book_ids = tuple(record.id for record in records)
        document_statement = select(BookDocumentRecord).where(
            BookDocumentRecord.book_id.in_(book_ids)
        )
        document_records = await self._session.scalars(document_statement)
        documents_by_book: defaultdict[UUID, list[BookDocument]] = defaultdict(list)
        for document_record in document_records:
            documents_by_book[document_record.book_id].append(
                _document_from_record(document_record)
            )
        return tuple(_catalog_book(record, documents_by_book[record.id]) for record in records)

    @override
    async def get_catalog_book(self, book_id: UUID) -> CatalogBookDetail | None:
        """Load one public book projection together with its ordered documents."""
        record = await self._session.get(BookRecord, book_id)
        if record is None:
            return None
        documents = await self.list_documents(book_id)
        return CatalogBookDetail(book=_catalog_book(record, documents), documents=documents)

    @override
    async def list_catalog_books(
        self,
        filters: BookListFilters,
        *,
        limit: int,
        after: BookOrderKey | None = None,
        before: BookOrderKey | None = None,
    ) -> BookWindow:
        """Load a stable forward or backward book window without offset drift."""
        if after is not None and before is not None:
            raise ValueError("after and before are mutually exclusive")
        statement: Select[tuple[BookRecord]] = select(BookRecord).where(
            *_book_filter_conditions(filters)
        )
        reverse = before is not None
        if after is not None:
            statement = statement.where(tuple_(*_BOOK_ORDER_COLUMNS) > _order_values(after))
        if before is not None:
            statement = statement.where(tuple_(*_BOOK_ORDER_COLUMNS) < _order_values(before))
        if reverse:
            statement = statement.order_by(*(column.desc() for column in _BOOK_ORDER_COLUMNS))
        else:
            statement = statement.order_by(*_BOOK_ORDER_COLUMNS)
        result = list((await self._session.scalars(statement.limit(limit + 1))).all())
        has_extra = len(result) > limit
        result = result[:limit]
        if reverse:
            result.reverse()
        items = await self._catalog_books_from_records(result)
        return BookWindow(
            items=items,
            has_previous=has_extra if reverse else after is not None,
            has_next=before is not None if reverse else has_extra,
        )

    @override
    async def count_catalog_books(self, filters: BookListFilters) -> int:
        """Count matching books exactly when explicitly requested by a client."""
        statement = select(func.count(BookRecord.id)).where(*_book_filter_conditions(filters))
        return await self._session.scalar(statement) or 0

    @override
    async def list_ready_book_options(self) -> tuple[CatalogBookOption, ...]:
        """Load retrieval filters from English books with an active ready document."""
        statement = (
            select(BookRecord)
            .join(BookDocumentRecord, BookDocumentRecord.book_id == BookRecord.id)
            .where(
                BookRecord.language == DocumentLanguage.ENGLISH,
                BookDocumentRecord.state == DocumentState.READY,
                BookDocumentRecord.activated_at.is_not(None),
            )
            .order_by(*_BOOK_ORDER_COLUMNS)
        )
        records = await self._session.scalars(statement)
        return tuple(
            CatalogBookOption(
                id=record.id,
                title=record.title,
                standard=record.standard,
                subject=record.subject,
            )
            for record in records
        )

    @override
    async def lock_idempotency_key(self, key: str) -> None:
        """Take a transaction-scoped PostgreSQL advisory lock for one client key."""
        statement = select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0)))
        await self._session.execute(statement)

    @override
    async def get_idempotency_snapshot(self, key: str) -> IdempotencySnapshot | None:
        """Load a completed response snapshot by its globally unique key."""
        record = await self._session.get(IdempotencyRecord, key)
        return None if record is None else _idempotency_from_record(record)

    @override
    async def add_idempotency_snapshot(self, snapshot: IdempotencySnapshot) -> None:
        """Flush a completed response snapshot without committing the transaction."""
        self._session.add(
            IdempotencyRecord(
                key=snapshot.key,
                operation=snapshot.operation,
                request_sha256=snapshot.request_sha256,
                response_status=snapshot.response_status,
                response_body=snapshot.response_body,
                response_headers=snapshot.response_headers,
                expires_at=snapshot.expires_at,
            )
        )
        await self._session.flush()

    @override
    async def add_queued_document(self, new_document: NewBookDocument) -> QueuedDocument:
        """Register a queued PDF and ingestion run in the caller's transaction."""
        document_record = BookDocumentRecord(
            book_id=new_document.book_id,
            edition=new_document.edition,
            source_filename=new_document.source_filename,
            media_type=new_document.media_type,
            source_artifact_key=new_document.source_artifact_key,
            source_sha256=new_document.source_sha256,
            file_size_bytes=new_document.file_size_bytes,
            state=DocumentState.QUEUED,
        )
        self._session.add(document_record)
        await self._session.flush()
        ingestion_record = IngestionRunRecord(document_id=document_record.id)
        self._session.add(ingestion_record)
        await self._session.flush()
        await self._session.refresh(document_record)
        await self._session.refresh(ingestion_record)
        return QueuedDocument(
            document=_document_from_record(document_record),
            ingestion_run=_ingestion_run_from_record(ingestion_record),
        )
