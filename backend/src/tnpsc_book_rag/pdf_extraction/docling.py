"""Compatibility exports for the standalone extraction runtime."""

from tnpsc_extraction.docling import DoclingExtractor, normalize_text
from tnpsc_extraction.models import (
    ExtractedAsset,
    ExtractedBlock,
    ExtractedPage,
    ExtractionBundle,
    ExtractionError,
)

__all__ = [
    "DoclingExtractor",
    "ExtractedAsset",
    "ExtractedBlock",
    "ExtractedPage",
    "ExtractionBundle",
    "ExtractionError",
    "normalize_text",
]
