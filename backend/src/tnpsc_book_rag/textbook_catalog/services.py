"""Application services for textbook catalog reads and accepted mutations."""

import base64
import binascii
import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from tnpsc_book_rag.artifact_storage import (
    ArtifactStorage,
    ArtifactStorageError,
    ArtifactTooLargeError,
)
from tnpsc_book_rag.artifact_storage.keys import source_pdf_key
from tnpsc_book_rag.telemetry_logging import run_in_thread_with_context
from tnpsc_book_rag.textbook_catalog.entities import NewBook, NewBookDocument
from tnpsc_book_rag.textbook_catalog.mutations import (
    AcceptedDocumentUpload,
    BookMutationResult,
    BookNotFoundError,
    CatalogMutationUnavailableError,
    DuplicateCatalogIdentifierError,
    DuplicateSourceError,
    IdempotencyConflictError,
    IdempotencySnapshot,
    MutationResult,
    PendingDocumentUpload,
    UnsupportedUploadMediaTypeError,
    UploadMutationResult,
    UploadTooLargeError,
)
from tnpsc_book_rag.textbook_catalog.ports import CatalogRepository
from tnpsc_book_rag.textbook_catalog.read_models import (
    BookListFilters,
    BookOrderKey,
    CatalogBook,
    CatalogBookDetail,
    CatalogFilterOptions,
    CatalogLibraryItem,
)
from tnpsc_book_rag.textbook_catalog.snapshots import (
    book_from_payload,
    book_payload,
    canonical_hash,
    upload_from_payload,
    upload_payload,
)
from tnpsc_book_rag.textbook_catalog.uploads import (
    inspect_pdf,
    normalize_edition,
    normalize_upload_filename,
)

_CURSOR_VERSION = 1
_MAX_CURSOR_LENGTH = 2_048
_CREATE_BOOK_OPERATION = "POST /v1/books"
type CursorDirection = Literal["next", "previous"]
type CatalogTransactionFactory = Callable[[], AbstractAsyncContextManager[CatalogRepository]]


class InvalidCursorError(ValueError):
    """Raised when an opaque cursor is malformed or belongs to other filters."""


@dataclass(frozen=True, slots=True)
class CatalogBookPage:
    """One public page with opaque adjacent-navigation cursors."""

    items: tuple[CatalogBook, ...]
    previous_cursor: str | None
    next_cursor: str | None
    total_items: int | None


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


def _filter_fingerprint(filters: BookListFilters) -> str:
    payload = {
        "endpoint": "books",
        "q": None if filters.query is None else filters.query.casefold(),
        "standards": sorted(filters.standards),
        "subjects": sorted(subject.casefold() for subject in filters.subjects),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _encode_cursor(
    direction: CursorDirection,
    key: BookOrderKey,
    fingerprint: str,
) -> str:
    payload = {
        "d": direction,
        "f": fingerprint,
        "k": [key.standard, key.subject, key.title, str(key.id)],
        "v": _CURSOR_VERSION,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_cursor(cursor: str, fingerprint: str) -> tuple[CursorDirection, BookOrderKey]:
    if not cursor or len(cursor) > _MAX_CURSOR_LENGTH:
        raise InvalidCursorError("cursor is invalid")
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"d", "f", "k", "v"}:
            raise InvalidCursorError("cursor is invalid")
        direction = payload["d"]
        key = payload["k"]
        if (
            payload["v"] != _CURSOR_VERSION
            or payload["f"] != fingerprint
            or direction not in ("next", "previous")
            or not isinstance(key, list)
            or len(key) != 4
            or not isinstance(key[0], int)
            or not isinstance(key[1], str)
            or not isinstance(key[2], str)
            or not isinstance(key[3], str)
        ):
            raise InvalidCursorError("cursor is invalid")
        order_key = BookOrderKey(
            standard=key[0],
            subject=key[1],
            title=key[2],
            id=UUID(key[3]),
        )
    except (
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ) as error:
        raise InvalidCursorError("cursor is invalid") from error
    return direction, order_key


class CatalogService:
    """Coordinate repository reads and keep transport concerns out of persistence."""

    def __init__(
        self,
        transactions: CatalogTransactionFactory,
        *,
        storage: ArtifactStorage | None = None,
        max_upload_bytes: int = 52_428_800,
        idempotency_retention_seconds: int = 86_400,
        ingestion_poll_after_seconds: int = 2,
    ) -> None:
        self._transactions = transactions
        self._storage = storage
        self._max_upload_bytes = max_upload_bytes
        self._idempotency_retention = timedelta(seconds=idempotency_retention_seconds)
        self._ingestion_poll_after_seconds = ingestion_poll_after_seconds

    @property
    def mutations_enabled(self) -> bool:
        """Return whether durable artifact storage is configured for mutations."""
        return self._storage is not None

    @staticmethod
    def _validate_replay(
        snapshot: IdempotencySnapshot,
        *,
        operation: str,
        request_sha256: str,
    ) -> None:
        if snapshot.operation != operation or snapshot.request_sha256 != request_sha256:
            raise IdempotencyConflictError(
                "idempotency key was already used for a different request"
            )

    async def create_book(self, new_book: NewBook, *, idempotency_key: str) -> BookMutationResult:
        """Create a conceptual textbook with transactionally durable response replay."""
        request_sha256 = canonical_hash(
            {
                "catalog_identifier": new_book.catalog_identifier,
                "language": new_book.language.value,
                "publisher": new_book.publisher,
                "standard": new_book.standard,
                "subject": new_book.subject,
                "title": new_book.title,
            }
        )
        try:
            async with self._transactions() as repository:
                await repository.lock_idempotency_key(idempotency_key)
                snapshot = await repository.get_idempotency_snapshot(idempotency_key)
                if snapshot is not None:
                    self._validate_replay(
                        snapshot,
                        operation=_CREATE_BOOK_OPERATION,
                        request_sha256=request_sha256,
                    )
                    return MutationResult(
                        value=book_from_payload(snapshot.response_body),
                        status_code=snapshot.response_status,
                        headers=dict(snapshot.response_headers),
                        replayed=True,
                    )
                if (
                    new_book.catalog_identifier is not None
                    and await repository.get_book_by_catalog_identifier(new_book.catalog_identifier)
                    is not None
                ):
                    raise DuplicateCatalogIdentifierError(
                        "catalog identifier is already registered"
                    )
                created = await repository.add_book(new_book)
                detail = await repository.get_catalog_book(created.id)
                if detail is None:
                    raise RuntimeError("created book projection is unavailable")
                headers = {"Location": f"/v1/books/{created.id}"}
                await repository.add_idempotency_snapshot(
                    IdempotencySnapshot(
                        key=idempotency_key,
                        operation=_CREATE_BOOK_OPERATION,
                        request_sha256=request_sha256,
                        response_status=201,
                        response_body=book_payload(detail.book),
                        response_headers=headers,
                        expires_at=datetime.now(UTC) + self._idempotency_retention,
                    )
                )
                return MutationResult(
                    value=detail.book,
                    status_code=201,
                    headers=headers,
                    replayed=False,
                )
        except IntegrityError as error:
            if _constraint_name(error) == "uq_books_catalog_identifier":
                raise DuplicateCatalogIdentifierError(
                    "catalog identifier is already registered"
                ) from error
            raise

    async def upload_document(
        self,
        book_id: UUID,
        upload: PendingDocumentUpload,
        *,
        idempotency_key: str,
    ) -> UploadMutationResult:
        """Store a bounded PDF and atomically queue its durable ingestion record."""
        if self._storage is None:
            raise CatalogMutationUnavailableError("artifact storage is not configured")
        media_type = upload.media_type.partition(";")[0].strip().lower()
        if media_type != "application/pdf":
            raise UnsupportedUploadMediaTypeError("declared upload media type is not PDF")
        filename = normalize_upload_filename(upload.filename)
        edition = normalize_edition(upload.edition)
        source_sha256, file_size_bytes = await run_in_thread_with_context(
            inspect_pdf,
            upload.source,
            self._max_upload_bytes,
        )
        artifact_key = source_pdf_key(source_sha256)
        operation = f"POST /v1/books/{book_id}/documents"
        request_sha256 = canonical_hash(
            {
                "book_id": str(book_id),
                "edition": edition,
                "filename": filename,
                "media_type": media_type,
                "source_sha256": source_sha256,
            }
        )
        try:
            async with self._transactions() as repository:
                await repository.lock_idempotency_key(idempotency_key)
                snapshot = await repository.get_idempotency_snapshot(idempotency_key)
                if snapshot is not None:
                    self._validate_replay(
                        snapshot,
                        operation=operation,
                        request_sha256=request_sha256,
                    )
                    return MutationResult(
                        value=upload_from_payload(snapshot.response_body),
                        status_code=snapshot.response_status,
                        headers=dict(snapshot.response_headers),
                        replayed=True,
                    )
                if await repository.get_book(book_id) is None:
                    raise BookNotFoundError("book does not exist")
                if await repository.get_document_by_checksum(source_sha256) is not None:
                    raise DuplicateSourceError("PDF checksum is already registered")
                try:
                    await self._storage.put(
                        artifact_key,
                        upload.source,
                        expected_sha256=source_sha256,
                        max_bytes=self._max_upload_bytes,
                    )
                except ArtifactTooLargeError as error:
                    raise UploadTooLargeError("upload exceeds the configured byte limit") from error
                except ArtifactStorageError as error:
                    raise CatalogMutationUnavailableError(
                        "artifact storage is unavailable"
                    ) from error
                queued = await repository.add_queued_document(
                    NewBookDocument(
                        book_id=book_id,
                        edition=edition,
                        source_filename=filename,
                        source_artifact_key=str(artifact_key),
                        source_sha256=source_sha256,
                        file_size_bytes=file_size_bytes,
                    )
                )
                accepted = AcceptedDocumentUpload(
                    document=queued.document,
                    ingestion_run=queued.ingestion_run,
                    poll_after_seconds=self._ingestion_poll_after_seconds,
                    document_url=f"/v1/documents/{queued.document.id}",
                    ingestion_run_url=f"/v1/ingestion-runs/{queued.ingestion_run.id}",
                )
                await repository.add_idempotency_snapshot(
                    IdempotencySnapshot(
                        key=idempotency_key,
                        operation=operation,
                        request_sha256=request_sha256,
                        response_status=202,
                        response_body=upload_payload(accepted),
                        response_headers={},
                        expires_at=datetime.now(UTC) + self._idempotency_retention,
                    )
                )
                return MutationResult(
                    value=accepted,
                    status_code=202,
                    headers={},
                    replayed=False,
                )
        except IntegrityError as error:
            if _constraint_name(error) == "uq_book_documents_source_sha256":
                raise DuplicateSourceError("PDF checksum is already registered") from error
            raise

    async def get_book(self, book_id: UUID) -> CatalogBookDetail | None:
        """Return one public catalog detail projection."""
        async with self._transactions() as repository:
            return await repository.get_catalog_book(book_id)

    async def get_filters(self) -> CatalogFilterOptions:
        """Derive retrieval filters from active ready English editions."""
        async with self._transactions() as repository:
            books = await repository.list_ready_book_options()
        standards = tuple(sorted({book.standard for book in books}))
        subjects_by_key: dict[str, str] = {}
        for book in books:
            subjects_by_key.setdefault(book.subject.casefold(), book.subject)
        subjects = tuple(subjects_by_key[key] for key in sorted(subjects_by_key))
        return CatalogFilterOptions(standards=standards, subjects=subjects, books=books)

    async def get_library(self) -> tuple[CatalogLibraryItem, ...]:
        """Return all PDF source documents joined with catalog book metadata."""
        async with self._transactions() as repository:
            return await repository.get_library()

    async def list_books(
        self,
        filters: BookListFilters,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> CatalogBookPage:
        """Return one filter-bound keyset page and optional exact total."""
        fingerprint = _filter_fingerprint(filters)
        after: BookOrderKey | None = None
        before: BookOrderKey | None = None
        if cursor is not None:
            direction, key = _decode_cursor(cursor, fingerprint)
            if direction == "next":
                after = key
            else:
                before = key
        async with self._transactions() as repository:
            window = await repository.list_catalog_books(
                filters,
                limit=limit,
                after=after,
                before=before,
            )
            total_items = await repository.count_catalog_books(filters) if include_count else None
        if cursor is not None and not window.items:
            raise InvalidCursorError("cursor no longer identifies a catalog page")
        previous_cursor = (
            _encode_cursor("previous", window.items[0].order_key, fingerprint)
            if window.has_previous and window.items
            else None
        )
        next_cursor = (
            _encode_cursor("next", window.items[-1].order_key, fingerprint)
            if window.has_next and window.items
            else None
        )
        return CatalogBookPage(
            items=window.items,
            previous_cursor=previous_cursor,
            next_cursor=next_cursor,
            total_items=total_items,
        )
