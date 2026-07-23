"""Compatibility exports for the standalone extraction runtime."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from tnpsc_extraction.chunking import chunk_pages, token_count
from tnpsc_extraction.models import (
    ExtractedChunk,
    ExtractedContentUnit,
    ExtractedRetrievalChunk,
    TextbookChunkingResult,
)

if TYPE_CHECKING:
    from tnpsc_extraction.textbook_chunking import TextbookChunker, TextbookChunkingConfig

_HEAVY_EXPORTS = {
    "TextbookChunker": ("tnpsc_extraction.textbook_chunking", "TextbookChunker"),
    "TextbookChunkingConfig": (
        "tnpsc_extraction.textbook_chunking",
        "TextbookChunkingConfig",
    ),
}

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
    from tnpsc_extraction.textbook_chunking import TextbookChunker

    return TextbookChunker(config).chunk_json(path)


def __getattr__(name: str) -> object:
    """Load worker-only chunking implementations only when requested."""
    try:
        module_name, attribute_name = _HEAVY_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
