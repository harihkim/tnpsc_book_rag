"""Tests for server-owned portable artifact key generation."""

from uuid import UUID

import pytest

from tnpsc_book_rag.storage import (
    ArtifactKey,
    InvalidArtifactChecksumError,
    InvalidArtifactKeyError,
    UnsupportedArtifactMediaTypeError,
    docling_json_key,
    extraction_package_key,
    image_asset_key,
    source_pdf_key,
)


def test_canonical_keys_do_not_include_caller_filenames() -> None:
    """Durable locations are derived only from IDs, checksums, and detected types."""
    checksum = "a" * 64
    document_id = UUID(int=1)
    ingestion_run_id = UUID(int=2)

    assert str(source_pdf_key(checksum)) == f"sources/aa/{checksum}.pdf"
    assert str(docling_json_key(document_id, ingestion_run_id)) == (
        "documents/00000000-0000-0000-0000-000000000001/"
        "runs/00000000-0000-0000-0000-000000000002/docling.json"
    )
    assert str(extraction_package_key(document_id, ingestion_run_id)).endswith(
        "/extraction-package.zip"
    )
    assert str(image_asset_key(checksum, "image/png; charset=binary")) == (
        f"assets/aa/{checksum}.png"
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/absolute/file.pdf",
        "../outside.pdf",
        "safe/../outside.pdf",
        "safe//file.pdf",
        "safe\\file.pdf",
        "C:/windows/file.pdf",
        "safe/.hidden",
        "safe/file.",
        "safe/%2e%2e/file.pdf",
        "safe/con.txt",
        "safe/contains space.pdf",
    ],
)
def test_artifact_key_rejects_nonportable_or_traversing_segments(value: str) -> None:
    """A validated key cannot be interpreted as an absolute or parent-relative path."""
    with pytest.raises(InvalidArtifactKeyError):
        ArtifactKey(value)


@pytest.mark.parametrize("value", ["A" * 64, "g" * 64, "a" * 63, "a" * 65])
def test_content_addressed_keys_require_canonical_sha256(value: str) -> None:
    """Checksums stored in keys match the lowercase database checksum invariant."""
    with pytest.raises(InvalidArtifactChecksumError):
        source_pdf_key(value)


def test_image_key_rejects_unknown_detected_media_type() -> None:
    """User filenames cannot smuggle an arbitrary asset extension into storage."""
    with pytest.raises(UnsupportedArtifactMediaTypeError):
        image_asset_key("a" * 64, "application/octet-stream")
