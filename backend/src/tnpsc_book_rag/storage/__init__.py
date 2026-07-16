"""Provider-neutral artifact storage contracts and local implementation."""

from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.storage.errors import (
    ArtifactChecksumMismatchError,
    ArtifactConflictError,
    ArtifactNotFoundError,
    ArtifactStorageError,
    ArtifactTooLargeError,
    InvalidArtifactChecksumError,
    InvalidArtifactKeyError,
    UnsafeArtifactPathError,
    UnsupportedArtifactMediaTypeError,
)
from tnpsc_book_rag.storage.keys import (
    docling_json_key,
    image_asset_key,
    source_pdf_key,
    thumbnail_asset_key,
    validate_sha256,
)
from tnpsc_book_rag.storage.local import LocalArtifactStorage
from tnpsc_book_rag.storage.models import ArtifactKey, ArtifactMetadata, ArtifactWriteResult
from tnpsc_book_rag.storage.ports import (
    ArtifactStorage,
    ArtifactStorageLifecycle,
    ReadableBinary,
    WritableBinary,
)


def create_artifact_storage(settings: Settings) -> LocalArtifactStorage:
    """Create the MVP local adapter from application settings."""
    return LocalArtifactStorage(settings.artifact_root)


__all__ = [
    "ArtifactChecksumMismatchError",
    "ArtifactConflictError",
    "ArtifactKey",
    "ArtifactMetadata",
    "ArtifactNotFoundError",
    "ArtifactStorage",
    "ArtifactStorageError",
    "ArtifactStorageLifecycle",
    "ArtifactTooLargeError",
    "ArtifactWriteResult",
    "InvalidArtifactChecksumError",
    "InvalidArtifactKeyError",
    "LocalArtifactStorage",
    "ReadableBinary",
    "UnsafeArtifactPathError",
    "UnsupportedArtifactMediaTypeError",
    "WritableBinary",
    "create_artifact_storage",
    "docling_json_key",
    "image_asset_key",
    "source_pdf_key",
    "thumbnail_asset_key",
    "validate_sha256",
]
