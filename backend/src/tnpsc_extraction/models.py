"""Dependency-light extraction records shared by the offline and app runtimes."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ChunkContentType(StrEnum):
    """Structural content represented by an extracted retrieval chunk."""

    PROSE = "prose"
    HEADING = "heading"
    LIST = "list"
    TABLE = "table"
    CAPTION = "caption"
    MIXED = "mixed"


class ContentUnitType(StrEnum):
    """Semantic parent types used to expand precise retrieval matches."""

    SECTION = "section"
    PROSE = "prose"
    DEFINITION = "definition"
    LAW = "law"
    SOLVED_EXAMPLE = "solved_example"
    ACTIVITY = "activity"
    TABLE = "table"
    LIST = "list"
    CAPTION = "caption"
    MIXED = "mixed"


class DisplayFormat(StrEnum):
    """Safe display formats emitted by extraction packages."""

    PLAIN_TEXT = "plain_text"
    MARKDOWN = "markdown"


class ExtractionError(RuntimeError):
    """Raised when a PDF cannot produce a usable digital text extraction."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ExtractedBlock:
    """One ordered Docling text/table block with source provenance."""

    text: str
    content_type: str
    page_index: int
    bbox: dict[str, object] | None
    char_span: tuple[int, int] | None
    heading_level: int | None = None


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    """Normalized page text plus the structure used by the chunker."""

    pdf_page_index: int
    width: float | None
    height: float | None
    raw_text: str
    normalized_text: str
    blocks: tuple[ExtractedBlock, ...]
    warnings: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class ExtractedAsset:
    """One preserved picture and its page-level Docling provenance."""

    ordinal: int
    page_index: int
    path: Path
    media_type: str
    width: int
    height: int
    caption: str | None
    bounding_box: dict[str, object] | None
    coordinate_origin: str | None
    source_reference: str
    provenance: dict[str, object]


@dataclass(frozen=True, slots=True)
class ExtractionBundle:
    """All derived files and records produced for one extraction run."""

    pages: tuple[ExtractedPage, ...]
    assets: tuple[ExtractedAsset, ...]
    docling_json_path: Path
    page_count: int
    docling_version: str
    config_fingerprint: str


@dataclass(frozen=True, slots=True)
class ExtractedChunk:
    """One page-contained retrieval chunk before persistence or embedding."""

    page_index: int
    sequence_number: int
    display_text: str
    embedding_text: str
    chapter_title: str | None
    section_path: tuple[str, ...]
    content_type: ChunkContentType
    token_count: int
    content_sha256: str
    provenance: dict[str, object]


@dataclass(frozen=True, slots=True)
class ExtractedContentUnit:
    """One semantic parent retained for deterministic evidence expansion."""

    local_id: str
    sequence_number: int
    unit_type: ContentUnitType
    display_text: str
    display_format: DisplayFormat
    structured_content: dict[str, object] | None
    section_path: tuple[str, ...]
    retrieval_eligible: bool
    exclusion_reason: str | None
    content_sha256: str
    page_indexes: tuple[int, ...]
    docling_refs: tuple[str, ...]
    provenance: dict[str, object]


@dataclass(frozen=True, slots=True)
class ExtractedRetrievalChunk:
    """One tokenizer-bounded child chunk used for embedding and retrieval."""

    local_id: str
    parent_local_id: str
    sequence_number: int
    display_text: str
    display_format: DisplayFormat
    embedding_text: str
    chapter_title: str | None
    section_path: tuple[str, ...]
    content_type: ChunkContentType
    token_count: int
    display_sha256: str
    embedding_sha256: str
    page_indexes: tuple[int, ...]
    docling_refs: tuple[str, ...]
    provenance: dict[str, object]


@dataclass(frozen=True, slots=True)
class TextbookChunkingResult:
    """Complete deterministic output of the parent-child textbook chunker."""

    content_units: tuple[ExtractedContentUnit, ...]
    chunks: tuple[ExtractedRetrievalChunk, ...]
    implementation_version: str
    tokenizer_identifier: str
    tokenizer_revision: str
    config_fingerprint: str
