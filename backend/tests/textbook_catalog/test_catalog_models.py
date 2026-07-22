"""Tests for stable catalog enum values consumed by future migrations."""

from tnpsc_book_rag.textbook_catalog import (
    AssetType,
    ChunkContentType,
    DocumentLanguage,
    DocumentState,
)


def test_catalog_enum_values_are_stable() -> None:
    """Persistence-facing enum values remain explicit and reviewable."""
    assert list(DocumentLanguage) == [DocumentLanguage.ENGLISH]
    assert {state.value for state in DocumentState} == {
        "uploaded",
        "queued",
        "extracting",
        "chunking",
        "embedding",
        "ready",
        "failed",
    }
    assert {asset_type.value for asset_type in AssetType} == {
        "image",
        "diagram",
        "map",
        "photograph",
        "figure",
        "unknown",
    }
    assert {content_type.value for content_type in ChunkContentType} == {
        "prose",
        "heading",
        "list",
        "table",
        "caption",
        "mixed",
    }
