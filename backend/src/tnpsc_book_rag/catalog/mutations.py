"""Transport-neutral contracts and failures for catalog mutations."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar

from tnpsc_book_rag.catalog.entities import BookDocument
from tnpsc_book_rag.catalog.read_models import CatalogBook
from tnpsc_book_rag.ingestion.entities import IngestionRun
from tnpsc_book_rag.storage.ports import ReadableBinary


class SeekableReadableBinary(ReadableBinary, Protocol):
    """Upload stream that can be rewound after bounded checksum inspection."""

    def seek(self, offset: int, whence: int = 0, /) -> int:
        """Move the current stream position."""
        ...


@dataclass(frozen=True, slots=True)
class PendingDocumentUpload:
    """Validated multipart metadata plus a caller-owned binary stream."""

    filename: str
    media_type: str
    edition: str
    source: SeekableReadableBinary


@dataclass(frozen=True, slots=True)
class QueuedDocument:
    """A source document and its atomically created durable queue record."""

    document: BookDocument
    ingestion_run: IngestionRun


@dataclass(frozen=True, slots=True)
class AcceptedDocumentUpload:
    """Queued upload plus the complete stable polling response metadata."""

    document: BookDocument
    ingestion_run: IngestionRun
    poll_after_seconds: int
    document_url: str
    ingestion_run_url: str


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class MutationResult[T]:
    """Mutation value plus replay metadata required by the HTTP boundary."""

    value: T
    status_code: int
    headers: dict[str, str]
    replayed: bool


@dataclass(frozen=True, slots=True)
class IdempotencySnapshot:
    """Completed response stored for exact mutation replay."""

    key: str
    operation: str
    request_sha256: str
    response_status: int
    response_body: dict[str, object]
    response_headers: dict[str, str]
    expires_at: datetime


class CatalogMutationError(ValueError):
    """Base for expected safe catalog mutation failures."""


class CatalogMutationUnavailableError(CatalogMutationError):
    """Raised when mutation dependencies are not configured."""


class BookNotFoundError(CatalogMutationError):
    """Raised when an upload targets an unknown book."""


class DuplicateCatalogIdentifierError(CatalogMutationError):
    """Raised when a board/catalog identifier already belongs to another book."""


class DuplicateSourceError(CatalogMutationError):
    """Raised when a PDF checksum is already registered anywhere in the corpus."""


class IdempotencyConflictError(CatalogMutationError):
    """Raised when a client key is reused for a different mutation request."""


class UnsupportedUploadMediaTypeError(CatalogMutationError):
    """Raised when declared or detected upload bytes are not PDF."""


class UploadTooLargeError(CatalogMutationError):
    """Raised when an upload exceeds the configured bounded stream size."""


type BookMutationResult = MutationResult[CatalogBook]
type UploadMutationResult = MutationResult[AcceptedDocumentUpload]
