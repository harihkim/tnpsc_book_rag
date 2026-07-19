"""Docling adapter unit tests that do not require model downloads."""

from pathlib import Path

import pytest

from tnpsc_book_rag.extraction.docling import DoclingExtractor, ExtractionError, normalize_text


def test_normalize_text_keeps_raw_input_separate_and_canonicalizes_layout_noise() -> None:
    """Unicode, line endings, whitespace, and excessive blank lines are normalized."""
    assert normalize_text("  Café\r\n\r\n\r\n occupies   space.  ") == "Café\n\noccupies space."


def test_extractor_fingerprint_changes_when_pipeline_options_change() -> None:
    """Run metadata can distinguish table/image configuration changes."""
    default = DoclingExtractor()
    without_tables = DoclingExtractor(do_table_structure=False)

    assert default.max_tokens == 400
    assert default.config_fingerprint != without_tables.config_fingerprint


def test_extraction_fingerprint_does_not_include_legacy_chunk_size() -> None:
    """Package v2 fingerprints extraction and chunking independently."""
    assert DoclingExtractor(max_tokens=256).config_fingerprint == DoclingExtractor(
        max_tokens=384
    ).config_fingerprint


def test_extractor_rejects_missing_source_without_loading_docling() -> None:
    """A missing source is a safe deterministic ingestion failure."""
    with pytest.raises(ExtractionError, match="source PDF does not exist") as error:
        DoclingExtractor().extract(Path("does-not-exist.pdf"), Path("out"))

    assert error.value.code == "source_not_found"
