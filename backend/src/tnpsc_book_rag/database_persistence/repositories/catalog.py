"""SQLAlchemy adapter for the application-facing catalog repository."""

import json
from collections import defaultdict
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast, override
from uuid import UUID

from sqlalchemy import Select, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from tnpsc_book_rag.artifact_storage.keys import docling_json_key
from tnpsc_book_rag.database_persistence.database import Database
from tnpsc_book_rag.database_persistence.models import (
    AssetRecord,
    BookDocumentRecord,
    BookRecord,
    ChunkPageRecord,
    ChunkRecord,
    ContentUnitPageRecord,
    ContentUnitRecord,
    IdempotencyRecord,
    IngestionRunRecord,
    PageRecord,
)
from tnpsc_book_rag.ingestion_pipeline.entities import IngestionRun, IngestionWorkItem
from tnpsc_book_rag.ingestion_pipeline.models import IngestionStage
from tnpsc_book_rag.ingestion_pipeline.status import IngestionRunStatus
from tnpsc_book_rag.pdf_extraction.chunking import (
    ExtractedChunk,
    ExtractedContentUnit,
    ExtractedRetrievalChunk,
    TextbookChunkingResult,
)
from tnpsc_book_rag.pdf_extraction.docling import ExtractionBundle
from tnpsc_book_rag.pdf_extraction.persistence import StoredAsset
from tnpsc_book_rag.textbook_catalog.entities import Book, BookDocument, NewBook, NewBookDocument
from tnpsc_book_rag.textbook_catalog.models import (
    AssetType,
    CatalogStatus,
    ChunkContentType,
    DocumentLanguage,
    DocumentState,
)
from tnpsc_book_rag.textbook_catalog.mutations import IdempotencySnapshot, QueuedDocument
from tnpsc_book_rag.textbook_catalog.ports import CatalogRepository
from tnpsc_book_rag.textbook_catalog.read_models import (
    BookListFilters,
    BookOrderKey,
    BookWindow,
    CatalogBook,
    CatalogBookDetail,
    CatalogBookOption,
    CatalogLibraryItem,
)
from tnpsc_extraction.models import ContentUnitType, DisplayFormat

_LEGACY_CHUNKER_FINGERPRINT = sha256(b"token-estimate-v1:max_tokens=400").hexdigest()


def _text_sha256(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _content_unit_sha256(
    display_text: str,
    display_format: DisplayFormat,
    structured_content: dict[str, object] | None,
) -> str:
    value = {
        "display_format": display_format.value,
        "display_text": display_text,
        "structured_content": structured_content,
    }
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return _text_sha256(payload)


def _legacy_parent_child_result(chunks: Sequence[ExtractedChunk]) -> TextbookChunkingResult:
    """Represent the transitional page chunker as one mixed parent per child."""
    parents: list[ExtractedContentUnit] = []
    children: list[ExtractedRetrievalChunk] = []
    for chunk in chunks:
        if chunk.sequence_number > 999999:
            raise ValueError("chunk sequence exceeds the package-local identifier limit")
        parent_local_id = f"U{chunk.sequence_number:06d}"
        parents.append(
            ExtractedContentUnit(
                local_id=parent_local_id,
                sequence_number=chunk.sequence_number,
                unit_type=ContentUnitType.MIXED,
                display_text=chunk.display_text,
                display_format=DisplayFormat.PLAIN_TEXT,
                structured_content=None,
                section_path=chunk.section_path,
                retrieval_eligible=True,
                exclusion_reason=None,
                content_sha256=_content_unit_sha256(
                    chunk.display_text,
                    DisplayFormat.PLAIN_TEXT,
                    None,
                ),
                page_indexes=(chunk.page_index,),
                docling_refs=(),
                provenance=chunk.provenance,
            )
        )
        children.append(
            ExtractedRetrievalChunk(
                local_id=f"C{chunk.sequence_number:06d}",
                parent_local_id=parent_local_id,
                sequence_number=chunk.sequence_number,
                display_text=chunk.display_text,
                display_format=DisplayFormat.PLAIN_TEXT,
                embedding_text=chunk.embedding_text,
                chapter_title=chunk.chapter_title,
                section_path=chunk.section_path,
                content_type=chunk.content_type,
                token_count=chunk.token_count,
                display_sha256=_text_sha256(chunk.display_text),
                embedding_sha256=_text_sha256(chunk.embedding_text),
                page_indexes=(chunk.page_index,),
                docling_refs=(),
                provenance=chunk.provenance,
            )
        )
    return TextbookChunkingResult(
        content_units=tuple(parents),
        chunks=tuple(children),
        implementation_version="legacy-page-chunker-v1",
        tokenizer_identifier="legacy-regex-token-estimate",
        tokenizer_revision="1",
        config_fingerprint=_LEGACY_CHUNKER_FINGERPRINT,
    )


def _validate_parent_child_graph(
    bundle: ExtractionBundle,
    chunking: TextbookChunkingResult,
    assets: Sequence[StoredAsset],
) -> None:
    """Reject an inconsistent graph before the caller-owned transaction writes rows."""
    page_indexes = [page.pdf_page_index for page in bundle.pages]
    known_pages = set(page_indexes)
    if len(page_indexes) != len(known_pages) or len(page_indexes) != bundle.page_count:
        raise ValueError("extraction pages must be unique and match the document page count")
    if not chunking.content_units or not chunking.chunks:
        raise ValueError("extraction must contain semantic parents and retrieval children")

    parents: dict[str, ExtractedContentUnit] = {}
    for sequence, parent in enumerate(chunking.content_units):
        if parent.sequence_number != sequence or parent.local_id != f"U{sequence:06d}":
            raise ValueError("content-unit identifiers and sequences must be contiguous")
        if parent.local_id in parents:
            raise ValueError("content-unit identifiers must be unique")
        if not parent.page_indexes or not set(parent.page_indexes) <= known_pages:
            raise ValueError("content-unit page provenance is missing or invalid")
        if parent.page_indexes != tuple(sorted(set(parent.page_indexes))):
            raise ValueError("content-unit page provenance must be ordered and unique")
        if parent.docling_refs != tuple(dict.fromkeys(parent.docling_refs)):
            raise ValueError("content-unit Docling references must be ordered and unique")
        expected_checksum = _content_unit_sha256(
            parent.display_text,
            parent.display_format,
            parent.structured_content,
        )
        if parent.content_sha256 != expected_checksum:
            raise ValueError("content-unit checksum does not match its persisted content")
        if parent.retrieval_eligible is (parent.exclusion_reason is not None):
            raise ValueError("content-unit retrieval eligibility is inconsistent")
        parents[parent.local_id] = parent

    parent_ids_with_children: set[str] = set()
    for sequence, child in enumerate(chunking.chunks):
        if child.sequence_number != sequence or child.local_id != f"C{sequence:06d}":
            raise ValueError("chunk identifiers and sequences must be contiguous")
        parent = parents.get(child.parent_local_id)
        if parent is None:
            raise ValueError("retrieval chunk references an unknown content unit")
        parent_ids_with_children.add(parent.local_id)
        if (child.content_type is ChunkContentType.TABLE) != (
            parent.unit_type is ContentUnitType.TABLE
        ):
            raise ValueError("retrieval chunk table type does not match its content unit")
        if child.token_count <= 0:
            raise ValueError("retrieval chunk token count must be positive")
        if not child.page_indexes or not set(child.page_indexes) <= set(parent.page_indexes):
            raise ValueError("chunk page provenance is missing or outside its parent")
        if child.page_indexes != tuple(sorted(set(child.page_indexes))):
            raise ValueError("chunk page provenance must be ordered and unique")
        if child.docling_refs != tuple(dict.fromkeys(child.docling_refs)) or not set(
            child.docling_refs
        ) <= set(parent.docling_refs):
            raise ValueError("chunk Docling references must be unique and inside its parent")
        if child.display_sha256 != _text_sha256(child.display_text):
            raise ValueError("chunk display checksum does not match its text")
        if child.embedding_sha256 != _text_sha256(child.embedding_text):
            raise ValueError("chunk embedding checksum does not match its text")

    if parent_ids_with_children != set(parents):
        raise ValueError("every content unit must have at least one retrieval child")
    if tuple(asset.source for asset in assets) != bundle.assets:
        raise ValueError("stored assets must exactly match the extraction bundle")
    if any(asset.source.page_index not in known_pages for asset in assets):
        raise ValueError("asset page provenance references an unknown page")


def _set_error_details(record: IngestionRunRecord, details: dict[str, str]) -> None:
    """Assign JSON diagnostics while keeping the SQLAlchemy descriptor out of typing."""
    cast(Any, record).error_details = details


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
    async def get_library(self) -> tuple[CatalogLibraryItem, ...]:
        """Load all PDF source documents joined with parent book catalog metadata."""
        statement = (
            select(BookDocumentRecord, BookRecord)
            .join(BookRecord, BookRecord.id == BookDocumentRecord.book_id)
            .order_by(
                BookRecord.standard,
                BookRecord.subject,
                BookRecord.title,
                BookDocumentRecord.created_at,
            )
        )
        results = await self._session.execute(statement)
        items: list[CatalogLibraryItem] = []
        for doc, book in results.all():
            items.append(
                CatalogLibraryItem(
                    document_id=doc.id,
                    book_id=book.id,
                    title=book.title,
                    standard=book.standard,
                    subject=book.subject,
                    edition=doc.edition,
                    publisher=book.publisher,
                    source_filename=doc.source_filename,
                    file_size_bytes=doc.file_size_bytes,
                    state=doc.state,
                    page_count=doc.page_count,
                    uploaded_at=doc.created_at,
                    active=doc.activated_at is not None,
                )
            )
        return tuple(items)

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

    async def claim_next_ingestion_run(self, worker_id: str) -> IngestionWorkItem | None:
        """Claim one queued run with PostgreSQL row locking and update its document state."""
        statement = (
            select(IngestionRunRecord)
            .where(IngestionRunRecord.status == IngestionRunStatus.QUEUED)
            .order_by(IngestionRunRecord.created_at, IngestionRunRecord.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        run_record = await self._session.scalar(statement)
        if run_record is None:
            return None
        document_record = await self._session.get(BookDocumentRecord, run_record.document_id)
        if document_record is None:
            run_record.status = IngestionRunStatus.FAILED
            run_record.completed_at = datetime.now(UTC)
            _set_error_details(
                run_record,
                {
                    "code": "document_missing",
                    "message": "source document is missing",
                },
            )
            await self._session.flush()
            return None
        book_record = await self._session.get(BookRecord, document_record.book_id)
        if book_record is None:
            run_record.status = IngestionRunStatus.FAILED
            run_record.completed_at = datetime.now(UTC)
            _set_error_details(
                run_record,
                {
                    "code": "book_missing",
                    "message": "catalog book is missing",
                },
            )
            await self._session.flush()
            return None
        now = datetime.now(UTC)
        run_record.status = IngestionRunStatus.RUNNING
        run_record.current_stage = IngestionStage.EXTRACTION
        run_record.worker_id = worker_id
        run_record.started_at = now
        document_record.state = DocumentState.EXTRACTING
        await self._session.flush()
        await self._session.refresh(run_record)
        await self._session.refresh(document_record)
        return IngestionWorkItem(
            book=_book_from_record(book_record),
            document=_document_from_record(document_record),
            ingestion_run=_ingestion_run_from_record(run_record),
        )

    async def persist_extraction(
        self,
        work_item: IngestionWorkItem,
        bundle: ExtractionBundle,
        chunks: Sequence[ExtractedChunk],
        assets: Sequence[StoredAsset],
    ) -> None:
        """Persist transitional v1 chunks as one mixed parent per retrieval child."""
        await self.persist_parent_child_extraction(
            work_item,
            bundle,
            _legacy_parent_child_result(chunks),
            assets,
        )

    async def persist_parent_child_extraction(
        self,
        work_item: IngestionWorkItem,
        bundle: ExtractionBundle,
        chunking: TextbookChunkingResult,
        assets: Sequence[StoredAsset],
        *,
        embedding_batch: Any = None,
        embedding_generator: Any = None,
    ) -> None:
        """Write one complete parent-child extraction graph in the caller's transaction."""
        _validate_parent_child_graph(bundle, chunking, assets)
        document_record = await self._session.get(BookDocumentRecord, work_item.document.id)
        run_record = await self._session.get(IngestionRunRecord, work_item.ingestion_run.id)
        if document_record is None or run_record is None:
            raise ValueError("claimed ingestion source records no longer exist")
        if work_item.book.id != document_record.book_id:
            raise ValueError("claimed catalog book does not own the source document")
        if run_record.document_id != document_record.id:
            raise ValueError("claimed ingestion run does not belong to the source document")
        page_records: dict[int, PageRecord] = {}
        for page in bundle.pages:
            record = PageRecord(
                document_id=document_record.id,
                ingestion_run_id=run_record.id,
                pdf_page_index=page.pdf_page_index,
                width=page.width,
                height=page.height,
                raw_text=page.raw_text,
                normalized_text=page.normalized_text,
                extraction_warnings=list(page.warnings),
            )
            self._session.add(record)
            page_records[page.pdf_page_index] = record
        await self._session.flush()
        for stored in assets:
            page = page_records[stored.source.page_index]
            caption = stored.source.caption
            self._session.add(
                AssetRecord(
                    page_id=page.id,
                    ingestion_run_id=run_record.id,
                    asset_type=AssetType.UNKNOWN,
                    artifact_key=str(stored.artifact_key),
                    mime_type=stored.source.media_type,
                    sha256=stored.sha256,
                    width=stored.source.width,
                    height=stored.source.height,
                    thumbnail_artifact_key=(
                        None
                        if stored.thumbnail_artifact_key is None
                        else str(stored.thumbnail_artifact_key)
                    ),
                    thumbnail_width=stored.thumbnail_width,
                    thumbnail_height=stored.thumbnail_height,
                    accessibility_status="caption_derived" if caption else "unavailable",
                    alt_text=caption,
                    alt_text_source="docling_caption" if caption else None,
                    caption=caption,
                    bounding_box=stored.source.bounding_box,
                    coordinate_origin=stored.source.coordinate_origin,
                    source_reference=stored.source.source_reference,
                    provenance=stored.source.provenance,
                )
            )
        await self._session.flush()

        content_unit_records: dict[str, ContentUnitRecord] = {}
        for content_unit in chunking.content_units:
            record = ContentUnitRecord(
                document_id=document_record.id,
                ingestion_run_id=run_record.id,
                source_local_id=content_unit.local_id,
                sequence_number=content_unit.sequence_number,
                unit_type=content_unit.unit_type,
                display_text=content_unit.display_text,
                display_format=content_unit.display_format,
                structured_content=content_unit.structured_content,
                section_path=list(content_unit.section_path),
                retrieval_eligible=content_unit.retrieval_eligible,
                exclusion_reason=content_unit.exclusion_reason,
                content_sha256=content_unit.content_sha256,
                docling_refs=list(content_unit.docling_refs),
                provenance=content_unit.provenance,
            )
            self._session.add(record)
            content_unit_records[content_unit.local_id] = record
        await self._session.flush()
        for content_unit in chunking.content_units:
            record = content_unit_records[content_unit.local_id]
            for span_order, page_index in enumerate(content_unit.page_indexes):
                self._session.add(
                    ContentUnitPageRecord(
                        content_unit_id=record.id,
                        page_id=page_records[page_index].id,
                        span_order=span_order,
                    )
                )
        await self._session.flush()

        chunk_records: list[tuple[ChunkRecord, ExtractedRetrievalChunk]] = []
        for chunk in chunking.chunks:
            page = page_records[chunk.page_indexes[0]]
            record = ChunkRecord(
                content_unit_id=content_unit_records[chunk.parent_local_id].id,
                page_id=page.id,
                document_id=document_record.id,
                ingestion_run_id=run_record.id,
                source_local_id=chunk.local_id,
                sequence_number=chunk.sequence_number,
                display_text=chunk.display_text,
                display_format=chunk.display_format,
                embedding_text=chunk.embedding_text,
                chapter_title=chunk.chapter_title,
                section_path=list(chunk.section_path),
                content_type=chunk.content_type,
                token_count=chunk.token_count,
                display_sha256=chunk.display_sha256,
                embedding_sha256=chunk.embedding_sha256,
                docling_refs=list(chunk.docling_refs),
                provenance=chunk.provenance,
            )
            self._session.add(record)
            chunk_records.append((record, chunk))
        await self._session.flush()
        for record, chunk in chunk_records:
            for span_order, page_index in enumerate(chunk.page_indexes):
                self._session.add(
                    ChunkPageRecord(
                        chunk_id=record.id,
                        page_id=page_records[page_index].id,
                        span_order=span_order,
                    )
                )
        now = datetime.now(UTC)
        document_record.docling_artifact_key = str(
            docling_json_key(document_record.id, run_record.id)
        )
        document_record.page_count = bundle.page_count

        # Persist embeddings if provided
        if embedding_batch is not None and embedding_generator is not None:
            from tnpsc_book_rag.database_persistence.models import ChunkEmbeddingRecord

            vectors = embedding_batch.vectors  # type: ignore[attr-defined]
            checksums = embedding_batch.content_checksums  # type: ignore[attr-defined]
            model_id = embedding_generator.model_identifier  # type: ignore[attr-defined]
            model_rev = embedding_generator.model_revision  # type: ignore[attr-defined]

            for idx, (record, _chunk) in enumerate(chunk_records):
                if idx < len(vectors):
                    self._session.add(
                        ChunkEmbeddingRecord(
                            chunk_id=record.id,
                            model_identifier=model_id,
                            model_revision=model_rev,
                            dimension=len(vectors[idx]),
                            content_sha256=checksums[idx],
                            embedding=vectors[idx],
                        )
                    )
            await self._session.flush()

            # Hand off activation atomically so a newer edition replaces the
            # previous active document without violating the one-active-edition
            # database constraint.
            await self._session.execute(
                update(BookDocumentRecord)
                .where(
                    BookDocumentRecord.book_id == document_record.book_id,
                    BookDocumentRecord.id != document_record.id,
                    BookDocumentRecord.activated_at.is_not(None),
                )
                .values(activated_at=None)
            )
            await self._session.flush()

            # Mark document as ready and activate it.
            document_record.state = DocumentState.READY
            document_record.activated_at = now
            run_record.current_stage = IngestionStage.ACTIVATION
            run_record.embedding_model_identifier = model_id
            run_record.embedding_model_revision = model_rev
        else:
            # No embeddings - mark as chunking complete
            document_record.state = DocumentState.CHUNKING
            run_record.current_stage = IngestionStage.CHUNKING

        run_record.status = IngestionRunStatus.SUCCEEDED
        run_record.docling_version = bundle.docling_version
        run_record.extraction_config_fingerprint = bundle.config_fingerprint
        run_record.chunker_version = chunking.implementation_version
        run_record.chunker_config_fingerprint = chunking.config_fingerprint
        run_record.chunker_tokenizer_identifier = chunking.tokenizer_identifier
        run_record.chunker_tokenizer_revision = chunking.tokenizer_revision
        run_record.completed_at = now
        run_record.warning_details = [warning for page in bundle.pages for warning in page.warnings]
        await self._session.flush()

    async def mark_ingestion_failed(
        self,
        run_id: UUID,
        *,
        code: str,
        message: str,
        completed_at: datetime,
    ) -> None:
        """Mark a run and its document failed with a sanitized diagnostic."""
        run_record = await self._session.get(IngestionRunRecord, run_id)
        if run_record is None:
            return
        document_record = await self._session.get(BookDocumentRecord, run_record.document_id)
        run_record.status = IngestionRunStatus.FAILED
        run_record.completed_at = completed_at
        _set_error_details(
            run_record,
            {
                "code": code,
                "message": message,
            },
        )
        if document_record is not None:
            document_record.state = DocumentState.FAILED
        await self._session.flush()
