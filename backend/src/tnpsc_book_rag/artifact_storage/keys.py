"""Server-owned canonical artifact key generation."""

import re
from uuid import UUID

from tnpsc_book_rag.artifact_storage.errors import (
    InvalidArtifactChecksumError,
    UnsupportedArtifactMediaTypeError,
)
from tnpsc_book_rag.artifact_storage.models import ArtifactKey

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_EXTENSIONS = {
    "image/bmp": "bmp",
    "image/gif": "gif",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/svg+xml": "svg",
    "image/tiff": "tiff",
    "image/webp": "webp",
}


def validate_sha256(value: str) -> str:
    """Return a canonical lowercase SHA-256 value or reject it."""
    if _SHA256.fullmatch(value) is None:
        msg = "SHA-256 must contain exactly 64 lowercase hexadecimal characters"
        raise InvalidArtifactChecksumError(msg)
    return value


def source_pdf_key(sha256: str) -> ArtifactKey:
    """Build a content-addressed key for an immutable original PDF."""
    checksum = validate_sha256(sha256)
    return ArtifactKey(f"sources/{checksum[:2]}/{checksum}.pdf")


def docling_json_key(document_id: UUID, ingestion_run_id: UUID) -> ArtifactKey:
    """Build a run-versioned key for lossless Docling JSON output."""
    return ArtifactKey(f"documents/{document_id}/runs/{ingestion_run_id}/docling.json")


def extraction_package_key(document_id: UUID, ingestion_run_id: UUID) -> ArtifactKey:
    """Build a run-versioned key for the immutable offline extraction package."""
    return ArtifactKey(f"documents/{document_id}/runs/{ingestion_run_id}/extraction-package.zip")


def image_asset_key(sha256: str, media_type: str) -> ArtifactKey:
    """Build a canonical content-addressed image key from a detected media type."""
    checksum = validate_sha256(sha256)
    normalized_media_type = media_type.partition(";")[0].strip().lower()
    extension = _IMAGE_EXTENSIONS.get(normalized_media_type)
    if extension is None:
        msg = "detected image media type is not supported for artifact preservation"
        raise UnsupportedArtifactMediaTypeError(msg)
    return ArtifactKey(f"assets/{checksum[:2]}/{checksum}.{extension}")


def thumbnail_asset_key(sha256: str, media_type: str = "image/png") -> ArtifactKey:
    """Build a content-addressed key for a canonical asset thumbnail."""
    checksum = validate_sha256(sha256)
    normalized_media_type = media_type.partition(";")[0].strip().lower()
    extension = _IMAGE_EXTENSIONS.get(normalized_media_type)
    if extension is None:
        msg = "thumbnail media type is not supported for artifact preservation"
        raise UnsupportedArtifactMediaTypeError(msg)
    return ArtifactKey(f"thumbnails/{checksum[:2]}/{checksum}.{extension}")
