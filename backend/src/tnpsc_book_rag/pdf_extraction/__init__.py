"""Lazy application compatibility exports for the extraction runtime."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tnpsc_book_rag.pdf_extraction.chunking import (
        TextbookChunker,
        TextbookChunkingConfig,
        TextbookChunkingResult,
        chunk_pages,
    )
    from tnpsc_book_rag.pdf_extraction.docling import (
        DoclingExtractor,
        ExtractedAsset,
        ExtractedPage,
        ExtractionBundle,
        ExtractionError,
    )
    from tnpsc_book_rag.pdf_extraction.importer import (
        MaterializedExtractionPackage,
        materialize_extraction_package,
    )
    from tnpsc_book_rag.pdf_extraction.package import (
        ExtractionPackageError,
        PackageBookMetadata,
        PackageFile,
        VerifiedExtractionPackage,
        verify_extraction_package,
    )
    from tnpsc_book_rag.pdf_extraction.persistence import StoredAsset

_EXPORTS = {
    "DoclingExtractor": ("tnpsc_book_rag.pdf_extraction.docling", "DoclingExtractor"),
    "ExtractedAsset": ("tnpsc_book_rag.pdf_extraction.docling", "ExtractedAsset"),
    "ExtractedPage": ("tnpsc_book_rag.pdf_extraction.docling", "ExtractedPage"),
    "ExtractionBundle": ("tnpsc_book_rag.pdf_extraction.docling", "ExtractionBundle"),
    "ExtractionError": ("tnpsc_book_rag.pdf_extraction.docling", "ExtractionError"),
    "ExtractionPackageError": (
        "tnpsc_book_rag.pdf_extraction.package",
        "ExtractionPackageError",
    ),
    "MaterializedExtractionPackage": (
        "tnpsc_book_rag.pdf_extraction.importer",
        "MaterializedExtractionPackage",
    ),
    "PackageBookMetadata": (
        "tnpsc_book_rag.pdf_extraction.package",
        "PackageBookMetadata",
    ),
    "PackageFile": ("tnpsc_book_rag.pdf_extraction.package", "PackageFile"),
    "StoredAsset": ("tnpsc_book_rag.pdf_extraction.persistence", "StoredAsset"),
    "TextbookChunker": ("tnpsc_book_rag.pdf_extraction.chunking", "TextbookChunker"),
    "TextbookChunkingConfig": (
        "tnpsc_book_rag.pdf_extraction.chunking",
        "TextbookChunkingConfig",
    ),
    "TextbookChunkingResult": (
        "tnpsc_book_rag.pdf_extraction.chunking",
        "TextbookChunkingResult",
    ),
    "VerifiedExtractionPackage": (
        "tnpsc_book_rag.pdf_extraction.package",
        "VerifiedExtractionPackage",
    ),
    "chunk_pages": ("tnpsc_book_rag.pdf_extraction.chunking", "chunk_pages"),
    "materialize_extraction_package": (
        "tnpsc_book_rag.pdf_extraction.importer",
        "materialize_extraction_package",
    ),
    "verify_extraction_package": (
        "tnpsc_book_rag.pdf_extraction.package",
        "verify_extraction_package",
    ),
}

__all__ = [
    "DoclingExtractor",
    "ExtractedAsset",
    "ExtractedPage",
    "ExtractionBundle",
    "ExtractionError",
    "ExtractionPackageError",
    "MaterializedExtractionPackage",
    "PackageBookMetadata",
    "PackageFile",
    "StoredAsset",
    "TextbookChunker",
    "TextbookChunkingConfig",
    "TextbookChunkingResult",
    "VerifiedExtractionPackage",
    "chunk_pages",
    "materialize_extraction_package",
    "verify_extraction_package",
]


def __getattr__(name: str) -> object:
    """Resolve extraction exports only when callers request them."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
