"""Immutable catalog values used outside the persistence adapter."""

from dataclasses import dataclass
from datetime import datetime
from re import fullmatch
from uuid import UUID

from tnpsc_book_rag.textbook_catalog.models import DocumentLanguage, DocumentState


def _normalized_text(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field} must contain at most {maximum} characters")
    return normalized


def _preserved_text(value: str, *, field: str, maximum: int | None = None) -> str:
    if not value.strip():
        raise ValueError(f"{field} must not be blank")
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"{field} must contain at most {maximum} characters")
    return value


@dataclass(frozen=True, slots=True)
class NewBook:
    """Validated values required to register one conceptual textbook."""

    title: str
    standard: int
    subject: str
    publisher: str
    language: DocumentLanguage = DocumentLanguage.ENGLISH
    catalog_identifier: str | None = None

    def __post_init__(self) -> None:
        if not 6 <= self.standard <= 10:
            raise ValueError("standard must be between 6 and 10")
        if self.language is not DocumentLanguage.ENGLISH:
            raise ValueError("language must be english")
        object.__setattr__(
            self,
            "title",
            _normalized_text(self.title, field="title", maximum=500),
        )
        object.__setattr__(
            self,
            "subject",
            _normalized_text(self.subject, field="subject", maximum=200),
        )
        object.__setattr__(
            self,
            "publisher",
            _normalized_text(self.publisher, field="publisher", maximum=300),
        )
        if self.catalog_identifier is not None:
            object.__setattr__(
                self,
                "catalog_identifier",
                _normalized_text(
                    self.catalog_identifier,
                    field="catalog_identifier",
                    maximum=200,
                ),
            )


@dataclass(frozen=True, slots=True)
class Book:
    """One persisted conceptual textbook without transport-specific projections."""

    id: UUID
    title: str
    standard: int
    subject: str
    language: DocumentLanguage
    publisher: str
    catalog_identifier: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class NewBookDocument:
    """Validated immutable source metadata for a newly stored textbook PDF."""

    book_id: UUID
    edition: str
    source_filename: str
    source_artifact_key: str
    source_sha256: str
    file_size_bytes: int
    media_type: str = "application/pdf"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "edition",
            _normalized_text(self.edition, field="edition", maximum=200),
        )
        _preserved_text(self.source_filename, field="source_filename", maximum=500)
        _preserved_text(self.source_artifact_key, field="source_artifact_key")
        if self.media_type != "application/pdf":
            raise ValueError("media_type must be application/pdf")
        if fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None:
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        if self.file_size_bytes <= 0:
            raise ValueError("file_size_bytes must be positive")


@dataclass(frozen=True, slots=True)
class BookDocument:
    """One persisted PDF edition and its current processing state."""

    id: UUID
    book_id: UUID
    edition: str
    source_filename: str
    media_type: str
    source_artifact_key: str
    docling_artifact_key: str | None
    source_sha256: str
    file_size_bytes: int
    page_count: int | None
    state: DocumentState
    activated_at: datetime | None
    created_at: datetime
    updated_at: datetime
