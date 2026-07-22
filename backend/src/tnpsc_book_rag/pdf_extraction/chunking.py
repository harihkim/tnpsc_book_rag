"""Compatibility exports for the standalone extraction runtime."""

from pathlib import Path

from tnpsc_extraction.chunking import chunk_pages, token_count
from tnpsc_extraction.models import (
    ExtractedChunk,
    ExtractedContentUnit,
    ExtractedRetrievalChunk,
    TextbookChunkingResult,
)
from tnpsc_extraction.textbook_chunking import TextbookChunker, TextbookChunkingConfig

__all__ = [
    "ExtractedChunk",
    "ExtractedContentUnit",
    "ExtractedRetrievalChunk",
    "TextbookChunker",
    "TextbookChunkingConfig",
    "TextbookChunkingResult",
    "chunk_docling_json",
    "chunk_pages",
    "token_count",
]


def chunk_docling_json(
    path: Path,
    config: TextbookChunkingConfig | None = None,
) -> TextbookChunkingResult:
    """Application helper that mirrors the offline package chunking path."""
    return TextbookChunker(config).chunk_json(path)
