"""Compatibility exports for the standalone extraction runtime."""

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
    "chunk_pages",
    "token_count",
]
