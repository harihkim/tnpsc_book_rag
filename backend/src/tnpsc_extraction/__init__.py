"""Standalone Docling extraction runtime with no application imports.

Public exports are resolved lazily so importing a lightweight model does not also
initialize Docling, Transformers, and PyTorch in API or migration processes.
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tnpsc_extraction.chunking import chunk_pages, token_count
    from tnpsc_extraction.docling import DoclingExtractor, normalize_text
    from tnpsc_extraction.models import (
        ChunkContentType,
        ContentUnitType,
        DisplayFormat,
        ExtractedAsset,
        ExtractedBlock,
        ExtractedChunk,
        ExtractedContentUnit,
        ExtractedPage,
        ExtractedRetrievalChunk,
        ExtractionBundle,
        ExtractionError,
        TextbookChunkingResult,
    )
    from tnpsc_extraction.textbook_chunking import TextbookChunker, TextbookChunkingConfig

_EXPORTS = {
    "ChunkContentType": ("tnpsc_extraction.models", "ChunkContentType"),
    "ContentUnitType": ("tnpsc_extraction.models", "ContentUnitType"),
    "DisplayFormat": ("tnpsc_extraction.models", "DisplayFormat"),
    "DoclingExtractor": ("tnpsc_extraction.docling", "DoclingExtractor"),
    "ExtractedAsset": ("tnpsc_extraction.models", "ExtractedAsset"),
    "ExtractedBlock": ("tnpsc_extraction.models", "ExtractedBlock"),
    "ExtractedChunk": ("tnpsc_extraction.models", "ExtractedChunk"),
    "ExtractedContentUnit": ("tnpsc_extraction.models", "ExtractedContentUnit"),
    "ExtractedPage": ("tnpsc_extraction.models", "ExtractedPage"),
    "ExtractedRetrievalChunk": ("tnpsc_extraction.models", "ExtractedRetrievalChunk"),
    "ExtractionBundle": ("tnpsc_extraction.models", "ExtractionBundle"),
    "ExtractionError": ("tnpsc_extraction.models", "ExtractionError"),
    "TextbookChunker": ("tnpsc_extraction.textbook_chunking", "TextbookChunker"),
    "TextbookChunkingConfig": (
        "tnpsc_extraction.textbook_chunking",
        "TextbookChunkingConfig",
    ),
    "TextbookChunkingResult": ("tnpsc_extraction.models", "TextbookChunkingResult"),
    "chunk_pages": ("tnpsc_extraction.chunking", "chunk_pages"),
    "normalize_text": ("tnpsc_extraction.docling", "normalize_text"),
    "token_count": ("tnpsc_extraction.chunking", "token_count"),
}

__all__ = [
    "ChunkContentType",
    "ContentUnitType",
    "DisplayFormat",
    "DoclingExtractor",
    "ExtractedAsset",
    "ExtractedBlock",
    "ExtractedChunk",
    "ExtractedContentUnit",
    "ExtractedPage",
    "ExtractedRetrievalChunk",
    "ExtractionBundle",
    "ExtractionError",
    "TextbookChunker",
    "TextbookChunkingConfig",
    "TextbookChunkingResult",
    "chunk_pages",
    "normalize_text",
    "token_count",
]


def __getattr__(name: str) -> object:
    """Load heavyweight extraction exports only when callers request them."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
