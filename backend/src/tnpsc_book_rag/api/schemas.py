"""Pydantic schemas exposed by implemented versioned routes."""

from datetime import datetime
from enum import IntEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from tnpsc_book_rag.catalog.models import CatalogStatus, DocumentLanguage, DocumentState
from tnpsc_book_rag.catalog.read_models import CatalogBook, CatalogBookDetail


class TextbookStandard(IntEnum):
    """Supported Tamil Nadu State Board school standards."""

    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10


TrimmedSubject = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
TrimmedQuery = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class StrictResponseModel(BaseModel):
    """Response base that prevents accidental contract expansion."""

    model_config = ConfigDict(extra="forbid")


class CapabilityFeatures(StrictResponseModel):
    """Client-visible implementation flags for the running deployment."""

    catalog_mutation: bool = False
    ingestion_inspection: bool = False
    semantic_search: bool = False
    answer_generation: bool = False
    answer_streaming: bool = False
    answer_recovery: bool = False


class CapabilityLimits(StrictResponseModel):
    """Public request and response limits used by frontend validation."""

    max_upload_bytes: int = Field(ge=1)
    max_query_characters: int = Field(ge=1)
    max_top_k: int = Field(ge=1)
    max_answer_characters_per_section: int = Field(ge=1)
    answer_timeout_seconds: int = Field(ge=1)
    answer_retention_seconds: int = Field(ge=1)
    thumbnail_max_edge_pixels: int = Field(ge=1)


class UploadCapabilities(StrictResponseModel):
    """Document constraints the frontend can enforce before upload."""

    accepted_media_types: list[str] = Field(min_length=1)
    requires_text_layer: bool


class Capabilities(StrictResponseModel):
    """Public capabilities document."""

    api_version: Literal["v1"] = "v1"
    features: CapabilityFeatures
    limits: CapabilityLimits
    upload: UploadCapabilities


class Book(StrictResponseModel):
    """Conceptual textbook plus derived document availability."""

    id: UUID
    title: str = Field(min_length=1, max_length=500)
    standard: TextbookStandard
    subject: str = Field(min_length=1, max_length=200)
    language: DocumentLanguage
    publisher: str = Field(min_length=1, max_length=300)
    catalog_identifier: str | None = Field(default=None, min_length=1, max_length=200)
    catalog_status: CatalogStatus
    document_count: int = Field(ge=0)
    active_document_id: UUID | None
    latest_document_id: UUID | None
    latest_document_state: DocumentState | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_catalog(cls, book: CatalogBook) -> Self:
        """Map a transport-neutral read model to its frozen response shape."""
        return cls.model_validate({field: getattr(book, field) for field in cls.model_fields})


class DocumentSummary(StrictResponseModel):
    """Public metadata for one registered source PDF."""

    id: UUID
    book_id: UUID
    edition: str = Field(min_length=1, max_length=200)
    source_filename: str
    media_type: Literal["application/pdf"]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    file_size_bytes: int = Field(ge=1)
    page_count: int | None = Field(default=None, ge=1)
    state: DocumentState
    activated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BookDetail(Book):
    """Book fields plus every registered edition in public order."""

    documents: list[DocumentSummary]

    @classmethod
    def from_catalog_detail(cls, detail: CatalogBookDetail) -> Self:
        """Flatten a catalog detail read model into the HTTP resource."""
        values = Book.from_catalog(detail.book).model_dump()
        values["documents"] = [
            DocumentSummary.model_validate(
                {field: getattr(document, field) for field in DocumentSummary.model_fields}
            )
            for document in detail.documents
        ]
        return cls.model_validate(values)


class BookPage(StrictResponseModel):
    """Adjacent-navigation catalog page."""

    items: list[Book]
    previous_cursor: str | None
    next_cursor: str | None
    total_items: int | None = Field(default=None, ge=0)


class CatalogBookOption(StrictResponseModel):
    """Ready textbook option for retrieval filtering."""

    id: UUID
    title: str
    standard: TextbookStandard
    subject: str


class CatalogFilters(StrictResponseModel):
    """Retrieval filter values derived from searchable textbook editions."""

    standards: list[TextbookStandard]
    subjects: list[str]
    books: list[CatalogBookOption]


class ValidationFieldError(StrictResponseModel):
    """One field-specific request validation error."""

    field: str
    message: str
    code: str


class Problem(StrictResponseModel):
    """Problem Details-compatible error returned by versioned routes."""

    type: str
    title: str
    status: int = Field(ge=400, le=599)
    detail: str
    instance: str
    code: str
    request_id: str
    errors: list[ValidationFieldError]


class BookListQuery(BaseModel):
    """Validated, repeatable query fields for catalog browsing."""

    model_config = ConfigDict(extra="forbid")

    standard: list[TextbookStandard] = Field(default_factory=list, max_length=5)
    subject: list[TrimmedSubject] = Field(default_factory=list, max_length=20)
    q: TrimmedQuery | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2_048)
    include_count: bool = False

    @model_validator(mode="after")
    def values_are_unique(self) -> Self:
        """Reject ambiguous repeated filters instead of silently changing them."""
        if len(self.standard) != len(set(self.standard)):
            raise ValueError("standard values must be unique")
        subjects = [subject.casefold() for subject in self.subject]
        if len(subjects) != len(set(subjects)):
            raise ValueError("subject values must be unique")
        return self
