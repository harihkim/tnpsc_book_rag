"""Bounded validation helpers for accepted textbook PDF uploads."""

import hashlib

from tnpsc_book_rag.textbook_catalog.mutations import (
    SeekableReadableBinary,
    UnsupportedUploadMediaTypeError,
    UploadTooLargeError,
)

_PDF_SIGNATURE = b"%PDF-"
_UPLOAD_INSPECTION_CHUNK_SIZE = 1024 * 1024


def normalize_upload_filename(filename: str) -> str:
    """Discard client paths and retain a bounded display filename."""
    normalized = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    if not normalized.strip() or "\x00" in normalized or len(normalized) > 500:
        raise ValueError("uploaded filename must contain between 1 and 500 safe characters")
    return normalized


def normalize_edition(edition: str) -> str:
    """Normalize the required human-facing edition label."""
    normalized = edition.strip()
    if not normalized or len(normalized) > 200:
        raise ValueError("edition must contain between 1 and 200 characters")
    return normalized


def inspect_pdf(source: SeekableReadableBinary, max_bytes: int) -> tuple[str, int]:
    """Stream a seekable upload once to enforce size, signature, and checksum."""
    source.seek(0)
    digest = hashlib.sha256()
    size_bytes = 0
    signature = b""
    try:
        while chunk := source.read(_UPLOAD_INSPECTION_CHUNK_SIZE):
            if not signature:
                signature = chunk[: len(_PDF_SIGNATURE)]
            size_bytes += len(chunk)
            if size_bytes > max_bytes:
                raise UploadTooLargeError("upload exceeds the configured byte limit")
            digest.update(chunk)
    finally:
        source.seek(0)
    if signature != _PDF_SIGNATURE:
        raise UnsupportedUploadMediaTypeError("upload bytes do not have a PDF signature")
    return digest.hexdigest(), size_bytes
