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
