"""Tests for durable catalog mutation and bounded PDF acceptance policies."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from tnpsc_book_rag.textbook_catalog.entities import Book, BookDocument, NewBook, NewBookDocument
from tnpsc_book_rag.textbook_catalog.models import CatalogStatus, DocumentState
from tnpsc_book_rag.textbook_catalog.mutations import (
    BookNotFoundError,
    DuplicateSourceError,
    IdempotencyConflictError,
    IdempotencySnapshot,
    PendingDocumentUpload,
    QueuedDocument,
    UnsupportedUploadMediaTypeError,
    UploadTooLargeError,
)
from tnpsc_book_rag.textbook_catalog.ports import CatalogRepository
from tnpsc_book_rag.textbook_catalog.read_models import CatalogBook, CatalogBookDetail
from tnpsc_book_rag.textbook_catalog.services import CatalogService
from tnpsc_book_rag.ingestion_pipeline.entities import IngestionRun
from tnpsc_book_rag.ingestion_pipeline.models import IngestionStage
from tnpsc_book_rag.ingestion_pipeline.status import IngestionRunStatus
from tnpsc_book_rag.artifact_storage import LocalArtifactStorage, source_pdf_key

_NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def _book_entity(book_id: UUID, new_book: NewBook) -> Book:
    return Book(
        id=book_id,
        title=new_book.title,
        standard=new_book.standard,
        subject=new_book.subject,
        language=new_book.language,
        publisher=new_book.publisher,
        catalog_identifier=new_book.catalog_identifier,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _catalog_book(book: Book, documents: tuple[BookDocument, ...] = ()) -> CatalogBook:
    latest = documents[-1] if documents else None
    return CatalogBook(
        id=book.id,
        title=book.title,
        standard=book.standard,
        subject=book.subject,
        language=book.language,
        publisher=book.publisher,
        catalog_identifier=book.catalog_identifier,
        catalog_status=CatalogStatus.PROCESSING if documents else CatalogStatus.EMPTY,
        document_count=len(documents),
        active_document_id=None,
        latest_document_id=None if latest is None else latest.id,
        latest_document_state=None if latest is None else latest.state,
        created_at=book.created_at,
        updated_at=book.updated_at,
    )


class FakeMutationRepository:
    """Small in-memory repository used to isolate mutation orchestration."""

    def __init__(self) -> None:
        self.books: dict[UUID, Book] = {}
        self.documents: dict[str, BookDocument] = {}
        self.snapshots: dict[str, IdempotencySnapshot] = {}
        self.book_add_count = 0
        self.queue_count = 0

    async def lock_idempotency_key(self, _: str) -> None: ...

    async def get_idempotency_snapshot(self, key: str) -> IdempotencySnapshot | None:
        return self.snapshots.get(key)

    async def add_idempotency_snapshot(self, snapshot: IdempotencySnapshot) -> None:
        self.snapshots[snapshot.key] = snapshot

    async def add_book(self, new_book: NewBook) -> Book:
        self.book_add_count += 1
        book = _book_entity(UUID(int=self.book_add_count), new_book)
        self.books[book.id] = book
        return book

    async def get_book(self, book_id: UUID) -> Book | None:
        return self.books.get(book_id)

    async def get_book_by_catalog_identifier(self, catalog_identifier: str) -> Book | None:
        return next(
            (book for book in self.books.values() if book.catalog_identifier == catalog_identifier),
            None,
        )

    async def get_catalog_book(self, book_id: UUID) -> CatalogBookDetail | None:
        book = self.books.get(book_id)
        if book is None:
            return None
        documents = tuple(
            document for document in self.documents.values() if document.book_id == book_id
        )
        return CatalogBookDetail(book=_catalog_book(book, documents), documents=documents)

    async def get_document_by_checksum(self, source_sha256: str) -> BookDocument | None:
        return self.documents.get(source_sha256)

    async def add_queued_document(self, new_document: NewBookDocument) -> QueuedDocument:
        self.queue_count += 1
        document = BookDocument(
            id=UUID(int=100 + self.queue_count),
            book_id=new_document.book_id,
            edition=new_document.edition,
            source_filename=new_document.source_filename,
            media_type=new_document.media_type,
            source_artifact_key=new_document.source_artifact_key,
            docling_artifact_key=None,
            source_sha256=new_document.source_sha256,
            file_size_bytes=new_document.file_size_bytes,
            page_count=None,
            state=DocumentState.QUEUED,
            activated_at=None,
            created_at=_NOW,
            updated_at=_NOW,
        )
        run = IngestionRun(
            id=UUID(int=200 + self.queue_count),
            document_id=document.id,
            status=IngestionRunStatus.QUEUED,
            current_stage=IngestionStage.QUEUED,
            retry_count=0,
            started_at=None,
            completed_at=None,
            warnings=(),
            error=None,
            created_at=_NOW,
            updated_at=_NOW,
        )
        self.documents[document.source_sha256] = document
        return QueuedDocument(document=document, ingestion_run=run)


def _service(
    repository: FakeMutationRepository,
    artifact_root: Path,
    *,
    max_upload_bytes: int = 1_024,
) -> CatalogService:
    @asynccontextmanager
    async def transactions() -> AsyncGenerator[CatalogRepository]:
        yield cast(CatalogRepository, repository)

    return CatalogService(
        transactions,
        storage=LocalArtifactStorage(artifact_root),
        max_upload_bytes=max_upload_bytes,
    )


@pytest.mark.anyio
async def test_create_book_replays_exact_snapshot_and_rejects_changed_request(
    tmp_path: Path,
) -> None:
    """A committed key replays one creation and cannot be reused for other input."""
    repository = FakeMutationRepository()
    service = _service(repository, tmp_path)
    request = NewBook(
        title="Science - Standard 8",
        standard=8,
        subject="Science",
        publisher="Tamil Nadu Textbook Corporation",
        catalog_identifier="science-8",
    )

    created = await service.create_book(request, idempotency_key="create-book-123")
    replayed = await service.create_book(request, idempotency_key="create-book-123")

    assert created.replayed is False
    assert replayed.replayed is True
    assert replayed.value == created.value
    assert replayed.headers == created.headers
    assert repository.book_add_count == 1
    with pytest.raises(IdempotencyConflictError):
        await service.create_book(
            NewBook(
                title="History - Standard 8",
                standard=8,
                subject="History",
                publisher="Tamil Nadu Textbook Corporation",
            ),
            idempotency_key="create-book-123",
        )


@pytest.mark.anyio
async def test_upload_is_bounded_content_addressed_queued_and_replayable(
    tmp_path: Path,
) -> None:
    """PDF acceptance stores immutable bytes and creates one document/run pair."""
    repository = FakeMutationRepository()
    book = await repository.add_book(
        NewBook(
            title="Science - Standard 8",
            standard=8,
            subject="Science",
            publisher="Tamil Nadu Textbook Corporation",
        )
    )
    service = _service(repository, tmp_path)
    pdf = b"%PDF-1.7\nphase-zero-fixture"

    accepted = await service.upload_document(
        book.id,
        PendingDocumentUpload(
            filename="folder\\science.pdf",
            media_type="application/pdf",
            edition=" 2025-2026 ",
            source=BytesIO(pdf),
        ),
        idempotency_key="upload-book-123",
    )
    repository.books.pop(book.id)
    replayed = await service.upload_document(
        book.id,
        PendingDocumentUpload(
            filename="folder\\science.pdf",
            media_type="application/pdf",
            edition=" 2025-2026 ",
            source=BytesIO(pdf),
        ),
        idempotency_key="upload-book-123",
    )
    repository.books[book.id] = book

    checksum = accepted.value.document.source_sha256
    assert accepted.value.document.state is DocumentState.QUEUED
    assert accepted.value.document.source_filename == "science.pdf"
    assert accepted.value.ingestion_run.status is IngestionRunStatus.QUEUED
    assert replayed.value == accepted.value
    assert replayed.replayed is True
    assert repository.queue_count == 1
    assert (await LocalArtifactStorage(tmp_path).stat(source_pdf_key(checksum))).size_bytes == len(
        pdf
    )
    with pytest.raises(DuplicateSourceError):
        await service.upload_document(
            book.id,
            PendingDocumentUpload(
                filename="science.pdf",
                media_type="application/pdf",
                edition="2026-2027",
                source=BytesIO(pdf),
            ),
            idempotency_key="upload-book-456",
        )


@pytest.mark.anyio
async def test_upload_rejects_unknown_book_media_signature_and_size(tmp_path: Path) -> None:
    """Expected upload failures happen before a queue record is created."""
    repository = FakeMutationRepository()
    service = _service(repository, tmp_path, max_upload_bytes=12)
    unknown_book = UUID(int=999)

    with pytest.raises(BookNotFoundError):
        await service.upload_document(
            unknown_book,
            PendingDocumentUpload("x.pdf", "application/pdf", "2026", BytesIO(b"%PDF-1.7")),
            idempotency_key="unknown-book-123",
        )

    book = await repository.add_book(
        NewBook("Science", 8, "Science", "Tamil Nadu Textbook Corporation")
    )
    with pytest.raises(UnsupportedUploadMediaTypeError):
        await service.upload_document(
            book.id,
            PendingDocumentUpload("x.pdf", "text/plain", "2026", BytesIO(b"%PDF-1.7")),
            idempotency_key="wrong-media-123",
        )
    with pytest.raises(UnsupportedUploadMediaTypeError):
        await service.upload_document(
            book.id,
            PendingDocumentUpload("x.pdf", "application/pdf", "2026", BytesIO(b"not-pdf")),
            idempotency_key="wrong-bytes-123",
        )
    with pytest.raises(UploadTooLargeError):
        await service.upload_document(
            book.id,
            PendingDocumentUpload(
                "x.pdf",
                "application/pdf",
                "2026",
                BytesIO(b"%PDF-" + b"x" * 20),
            ),
            idempotency_key="large-file-123",
        )
    assert repository.queue_count == 0
