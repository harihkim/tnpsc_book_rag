"""Pydantic schemas exposed by implemented versioned routes."""

from datetime import datetime
from enum import IntEnum
from typing import Annotated, Literal, Self, override
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from tnpsc_book_rag.debug_inspection import models as inspection_models
from tnpsc_book_rag.ingestion_pipeline.models import IngestionStage
from tnpsc_book_rag.ingestion_pipeline.status import IngestionRunStatus
from tnpsc_book_rag.textbook_catalog.models import (
    AssetType,
    CatalogStatus,
    ChunkContentType,
    DocumentLanguage,
    DocumentState,
)
from tnpsc_book_rag.textbook_catalog.read_models import (
    CatalogBook,
    CatalogBookDetail,
    CatalogLibraryItem,
)


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
TrimmedTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
TrimmedPublisher = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
]
TrimmedIdentifier = Annotated[
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


class CreateBookRequest(BaseModel):
    """Closed request body for registering one conceptual textbook."""

    model_config = ConfigDict(extra="forbid")

    title: TrimmedTitle
    standard: TextbookStandard
    subject: TrimmedSubject
    language: DocumentLanguage = DocumentLanguage.ENGLISH
    publisher: TrimmedPublisher
    catalog_identifier: TrimmedIdentifier | None = None


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

    @classmethod
    def from_document(cls, document: object) -> Self:
        """Map an immutable application document to its public response fields."""
        return cls.model_validate({field: getattr(document, field) for field in cls.model_fields})


class IngestionRun(StrictResponseModel):
    """Sanitized public state for one durable ingestion attempt."""

    id: UUID
    document_id: UUID
    status: IngestionRunStatus
    current_stage: IngestionStage
    retry_count: int = Field(ge=0)
    started_at: datetime | None
    completed_at: datetime | None
    warnings: list["IngestionIssue"]
    error: "IngestionIssue | None"
    created_at: datetime
    updated_at: datetime


class IngestionIssue(StrictResponseModel):
    """Sanitized ingestion diagnostic with optional stage and page provenance."""

    code: str
    message: str
    stage: IngestionStage | None
    pdf_page_index: int | None = Field(default=None, ge=0)


class BookReference(StrictResponseModel):
    """Minimal catalog identity included in the global operations table."""

    id: UUID
    title: str
    standard: TextbookStandard
    subject: str


class DocumentReference(StrictResponseModel):
    """Minimal source-document identity included in ingestion operations."""

    id: UUID
    edition: str
    source_filename: str
    state: DocumentState


class IngestionRunDetailResponse(StrictResponseModel):
    """Polling resource plus the server-recommended interval."""

    ingestion_run: IngestionRun
    poll_after_seconds: int = Field(ge=1)


class IngestionOperationItem(StrictResponseModel):
    """One global ingestion operations row."""

    ingestion_run: IngestionRun
    document: DocumentReference
    book: BookReference


class DocumentDetail(DocumentSummary):
    """Source document with its newest ingestion attempt."""

    latest_ingestion_run: IngestionRun | None

    @classmethod
    def from_inspection(cls, detail: inspection_models.DocumentInspection) -> Self:
        values = DocumentSummary.from_document(detail.document).model_dump()
        values["latest_ingestion_run"] = detail.latest_ingestion_run
        return cls.model_validate(values, from_attributes=True)


class UploadLinks(StrictResponseModel):
    """Polling resources returned when an upload is accepted."""

    document: str = Field(pattern=r"^/v1/documents/")
    ingestion_run: str = Field(pattern=r"^/v1/ingestion-runs/")


class DocumentUploadAccepted(StrictResponseModel):
    """Durable queue acceptance response; extraction has not completed yet."""

    document: DocumentSummary
    ingestion_run: IngestionRun
    poll_after_seconds: int = Field(ge=1)
    links: UploadLinks


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


class LibraryItem(StrictResponseModel):
    """PDF source document joined with parent textbook catalog metadata."""

    document_id: UUID
    book_id: UUID
    title: str
    standard: TextbookStandard
    subject: str
    edition: str
    publisher: str
    source_filename: str
    file_size_bytes: int = Field(ge=1)
    state: DocumentState
    page_count: int | None = Field(default=None, ge=1)
    uploaded_at: datetime
    active: bool

    @classmethod
    def from_catalog_item(cls, item: CatalogLibraryItem) -> Self:
        """Map a catalog library read model to the API schema."""
        return cls(
            document_id=item.document_id,
            book_id=item.book_id,
            title=item.title,
            standard=TextbookStandard(item.standard),
            subject=item.subject,
            edition=item.edition,
            publisher=item.publisher,
            source_filename=item.source_filename,
            file_size_bytes=item.file_size_bytes,
            state=item.state,
            page_count=item.page_count,
            uploaded_at=item.uploaded_at,
            active=item.active,
        )


class LibraryResponse(StrictResponseModel):
    """Complete list of library PDF items."""

    items: list[LibraryItem]


class IngestionOperationPage(StrictResponseModel):
    """Adjacent-navigation global ingestion operations page."""

    items: list[IngestionOperationItem]
    previous_cursor: str | None
    next_cursor: str | None
    total_items: int | None = Field(default=None, ge=0)


class IngestionRunPage(StrictResponseModel):
    """Adjacent-navigation ingestion history for one source document."""

    items: list[IngestionRun]
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


class PaginationQuery(BaseModel):
    """Common bounded keyset fields shared by administrative lists."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2_048)
    include_count: bool = False


class IngestionRunListQuery(PaginationQuery):
    """Filters for the global ingestion operations view."""

    status: list[IngestionRunStatus] = Field(default_factory=list, max_length=4)
    stage: list[IngestionStage] = Field(default_factory=list, max_length=5)
    book_id: UUID | None = None
    document_id: UUID | None = None

    @model_validator(mode="after")
    def values_are_unique(self) -> Self:
        if len(self.status) != len(set(self.status)):
            raise ValueError("status values must be unique")
        if len(self.stage) != len(set(self.stage)):
            raise ValueError("stage values must be unique")
        return self


class ChunkListQuery(PaginationQuery):
    """Document chunk pagination plus optional page provenance filter."""

    page_id: UUID | None = None


class PageSummary(StrictResponseModel):
    """Bounded page metadata for inspection lists."""

    id: UUID
    document_id: UUID
    pdf_page_index: int = Field(ge=0)
    printed_page_label: str | None = Field(default=None, max_length=100)
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    warning_count: int = Field(ge=0)
    created_at: datetime


class PageSummaryPage(StrictResponseModel):
    """Adjacent-navigation page summaries in PDF order."""

    items: list[PageSummary]
    previous_cursor: str | None
    next_cursor: str | None
    total_items: int | None = Field(default=None, ge=0)


PrintedPageLabel = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]


class UpdatePageRequest(BaseModel):
    """Only mutable human-facing page metadata in API v1."""

    model_config = ConfigDict(extra="forbid")

    printed_page_label: PrintedPageLabel | None


class BoundingBox(StrictResponseModel):
    """Canonical PDF-page rectangle."""

    x_min: float = Field(ge=0)
    y_min: float = Field(ge=0)
    x_max: float = Field(ge=0)
    y_max: float = Field(ge=0)
    coordinate_origin: Literal["top_left", "bottom_left"]


class AssetReference(StrictResponseModel):
    """Asset rendering and accessibility metadata embedded in source views."""

    id: UUID
    asset_type: AssetType
    caption: str | None
    alt_text: str | None
    alt_text_source: Literal["caption", "manual", "unavailable", "not_applicable"]
    is_decorative: bool
    pixel_width: int | None = Field(default=None, ge=1)
    pixel_height: int | None = Field(default=None, ge=1)
    content_url: str = Field(pattern=r"^/v1/assets/[^/]+/content$")
    thumbnail_url: str | None = Field(default=None, pattern=r"^/v1/assets/[^/]+/thumbnail$")
    thumbnail_pixel_width: int | None = Field(default=None, ge=1)
    thumbnail_pixel_height: int | None = Field(default=None, ge=1)

    @classmethod
    def from_inspection(cls, asset: inspection_models.AssetInspection) -> Self:
        has_thumbnail = (
            asset.thumbnail_pixel_width is not None and asset.thumbnail_pixel_height is not None
        )
        return cls(
            id=asset.id,
            asset_type=asset.asset_type,
            caption=asset.caption,
            alt_text=asset.alt_text,
            alt_text_source=asset.alt_text_source,
            is_decorative=asset.is_decorative,
            pixel_width=asset.pixel_width,
            pixel_height=asset.pixel_height,
            content_url=f"/v1/assets/{asset.id}/content",
            thumbnail_url=f"/v1/assets/{asset.id}/thumbnail" if has_thumbnail else None,
            thumbnail_pixel_width=asset.thumbnail_pixel_width,
            thumbnail_pixel_height=asset.thumbnail_pixel_height,
        )


class Asset(AssetReference):
    """Complete asset metadata returned by inspection endpoints."""

    page_id: UUID
    mime_type: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bounding_box: BoundingBox | None
    created_at: datetime

    @classmethod
    @override
    def from_inspection(cls, asset: inspection_models.AssetInspection) -> Self:
        values = AssetReference.from_inspection(asset).model_dump()
        values.update(
            {
                "page_id": asset.page_id,
                "mime_type": asset.mime_type,
                "sha256": asset.sha256,
                "bounding_box": asset.bounding_box,
                "created_at": asset.created_at,
            }
        )
        return cls.model_validate(values, from_attributes=True)


class ChunkSummary(StrictResponseModel):
    """Human-facing child chunk without private embedding input."""

    id: UUID
    page_id: UUID
    document_id: UUID
    sequence_number: int = Field(ge=0)
    display_text: str
    chapter_title: str | None
    section_path: list[str]
    content_type: ChunkContentType
    token_count: int = Field(ge=0)
    created_at: datetime


class ChunkPage(StrictResponseModel):
    """Adjacent-navigation chunk summaries in document sequence order."""

    items: list[ChunkSummary]
    previous_cursor: str | None
    next_cursor: str | None
    total_items: int | None = Field(default=None, ge=0)


class PageDetail(PageSummary):
    """Complete extracted page with warnings, children, and assets."""

    raw_text: str
    normalized_text: str
    warnings: list[IngestionIssue]
    chunks: list[ChunkSummary]
    assets: list[Asset]

    @classmethod
    def from_inspection(cls, detail: inspection_models.PageDetail) -> Self:
        values = {field: getattr(detail.summary, field) for field in PageSummary.model_fields}
        values.update(
            {
                "raw_text": detail.raw_text,
                "normalized_text": detail.normalized_text,
                "warnings": detail.warnings,
                "chunks": detail.chunks,
                "assets": [Asset.from_inspection(asset) for asset in detail.assets],
            }
        )
        return cls.model_validate(values, from_attributes=True)
