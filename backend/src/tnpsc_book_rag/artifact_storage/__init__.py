"""Provider-neutral artifact storage contracts and local implementation."""

from tnpsc_book_rag.artifact_storage.errors import (
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
from tnpsc_book_rag.artifact_storage.keys import (
    docling_json_key,
    extraction_package_key,
    image_asset_key,
    source_pdf_key,
    thumbnail_asset_key,
    validate_sha256,
)
from tnpsc_book_rag.artifact_storage.local import LocalArtifactStorage
from tnpsc_book_rag.artifact_storage.models import (
    ArtifactKey,
    ArtifactMetadata,
    ArtifactWriteResult,
)
from tnpsc_book_rag.artifact_storage.ports import (
    ArtifactStorage,
    ArtifactStorageLifecycle,
    ReadableBinary,
    WritableBinary,
)
from tnpsc_book_rag.artifact_storage.s3 import S3ArtifactStorage
from tnpsc_book_rag.config import Settings


def create_artifact_storage(settings: Settings) -> ArtifactStorage:
    """Create the storage adapter (local or S3) from application settings."""
    if settings.storage_backend == "s3":
        if (
            not settings.s3_endpoint_url
            or not settings.s3_bucket
            or not settings.s3_access_key_id
            or not settings.s3_secret_access_key
        ):
            msg = (
                "S3 storage requires s3_endpoint_url, s3_bucket, s3_access_key_id, "
                "and s3_secret_access_key"
            )
            raise ValueError(msg)
        return S3ArtifactStorage(
            endpoint_url=str(settings.s3_endpoint_url),
            bucket=settings.s3_bucket,
            access_key_id=settings.s3_access_key_id.get_secret_value(),
            secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            region_name=settings.s3_region,
            prefix=settings.s3_prefix,
        )
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
    "S3ArtifactStorage",
    "UnsafeArtifactPathError",
    "UnsupportedArtifactMediaTypeError",
    "WritableBinary",
    "create_artifact_storage",
    "docling_json_key",
    "extraction_package_key",
    "image_asset_key",
    "source_pdf_key",
    "thumbnail_asset_key",
    "validate_sha256",
]
