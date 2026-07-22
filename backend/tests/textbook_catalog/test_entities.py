"""Tests for catalog values that guard non-HTTP callers."""

from collections.abc import Callable
from uuid import uuid4

import pytest

from tnpsc_book_rag.textbook_catalog import NewBook, NewBookDocument


def test_new_book_normalizes_catalog_text() -> None:
    """Application values reach persistence with the API's whitespace policy applied."""
    book = NewBook(
        title="  Science — Standard 8  ",
        standard=8,
        subject=" Science ",
        publisher=" Tamil Nadu Textbook Corporation ",
        catalog_identifier=" SCI-8 ",
    )

    assert book.title == "Science — Standard 8"
    assert book.subject == "Science"
    assert book.publisher == "Tamil Nadu Textbook Corporation"
    assert book.catalog_identifier == "SCI-8"


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: NewBook(" ", 8, "Science", "Tamil Nadu Textbook Corporation"),
            "title must not be blank",
        ),
        (
            lambda: NewBook("Science", 5, "Science", "Tamil Nadu Textbook Corporation"),
            "standard must be between 6 and 10",
        ),
        (
            lambda: NewBook("Science", 8, "x" * 201, "Tamil Nadu Textbook Corporation"),
            "subject must contain at most 200 characters",
        ),
        (
            lambda: NewBook("Science", 8, "Science", ""),
            "publisher must not be blank",
        ),
        (
            lambda: NewBook(
                "Science",
                8,
                "Science",
                "Tamil Nadu Textbook Corporation",
                catalog_identifier=" ",
            ),
            "catalog_identifier must not be blank",
        ),
    ],
)
def test_new_book_rejects_values_outside_catalog_invariants(
    factory: Callable[[], NewBook],
    message: str,
) -> None:
    """Domain construction cannot bypass constraints enforced by PostgreSQL."""
    with pytest.raises(ValueError, match=message):
        factory()


def test_new_document_normalizes_metadata_but_preserves_source_filename() -> None:
    """Edition is user metadata while the original uploaded filename remains diagnostic data."""
    document = NewBookDocument(
        book_id=uuid4(),
        edition=" 2025-2026 ",
        source_filename=" science standard 8.pdf ",
        source_artifact_key="sources/document/source.pdf",
        source_sha256="a" * 64,
        file_size_bytes=1024,
    )

    assert document.edition == "2025-2026"
    assert document.source_filename == " science standard 8.pdf "


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: _new_document(edition=""),
            "edition must not be blank",
        ),
        (
            lambda: _new_document(source_filename=" "),
            "source_filename must not be blank",
        ),
        (
            lambda: _new_document(source_artifact_key=""),
            "source_artifact_key must not be blank",
        ),
        (
            lambda: _new_document(source_sha256="A" * 64),
            "source_sha256 must be a lowercase SHA-256 digest",
        ),
        (
            lambda: _new_document(source_sha256="a" * 63),
            "source_sha256 must be a lowercase SHA-256 digest",
        ),
        (
            lambda: _new_document(file_size_bytes=0),
            "file_size_bytes must be positive",
        ),
        (
            lambda: _new_document(media_type="image/png"),
            "media_type must be application/pdf",
        ),
    ],
)
def test_new_document_rejects_unsafe_source_metadata(
    factory: Callable[[], NewBookDocument],
    message: str,
) -> None:
    """Invalid immutable metadata fails before a database transaction starts."""
    with pytest.raises(ValueError, match=message):
        factory()


def _new_document(
    *,
    edition: str = "2026",
    source_filename: str = "science.pdf",
    source_artifact_key: str = "sources/document/source.pdf",
    source_sha256: str = "a" * 64,
    file_size_bytes: int = 1024,
    media_type: str = "application/pdf",
) -> NewBookDocument:
    return NewBookDocument(
        book_id=uuid4(),
        edition=edition,
        source_filename=source_filename,
        source_artifact_key=source_artifact_key,
        source_sha256=source_sha256,
        file_size_bytes=file_size_bytes,
        media_type=media_type,
    )
