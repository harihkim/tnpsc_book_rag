"""Deterministic structure-aware chunking tests."""

from tnpsc_book_rag.textbook_catalog.models import ChunkContentType
from tnpsc_book_rag.pdf_extraction.chunking import chunk_pages, token_count
from tnpsc_book_rag.pdf_extraction.docling import ExtractedBlock, ExtractedPage


def _page(page_index: int, *blocks: ExtractedBlock) -> ExtractedPage:
    return ExtractedPage(
        pdf_page_index=page_index,
        width=612.0,
        height=792.0,
        raw_text="\n\n".join(block.text for block in blocks),
        normalized_text="\n\n".join(block.text for block in blocks),
        blocks=blocks,
        warnings=(),
    )


def test_token_estimate_is_positive_and_deterministic() -> None:
    """The conservative estimator is stable for empty and punctuation-only text."""
    assert token_count("") == 1
    assert token_count("Matter occupies space.") == token_count("Matter occupies space.")
    assert token_count("...") == 3


def test_chunking_preserves_headings_page_boundaries_and_provenance() -> None:
    """Chunks retain section context and never silently cross a PDF page."""
    page_one = _page(
        0,
        ExtractedBlock("Matter", "heading", 0, None, None, heading_level=1),
        ExtractedBlock("Matter occupies space and has mass.", "prose", 0, None, (0, 35)),
    )
    page_two = _page(
        1,
        ExtractedBlock("States of matter", "heading", 1, None, None, heading_level=2),
        ExtractedBlock("Solids retain their shape.", "prose", 1, None, (0, 27)),
    )

    chunks = chunk_pages((page_one, page_two), max_tokens=400)

    assert [chunk.page_index for chunk in chunks] == [0, 1]
    assert [chunk.sequence_number for chunk in chunks] == [0, 1]
    assert chunks[0].chapter_title == "Matter"
    assert chunks[0].section_path == ("Matter",)
    assert "Matter > Matter occupies" not in chunks[0].embedding_text
    assert chunks[0].content_type is ChunkContentType.MIXED
    assert chunks[0].provenance["blocks"]
    assert chunks[1].section_path == ("Matter", "States of matter")


def test_chunking_splits_oversized_blocks_without_crossing_pages() -> None:
    """An oversized prose block is split into bounded, ordered fragments."""
    words = " ".join(f"word{i}" for i in range(40))
    page = _page(3, ExtractedBlock(words, "prose", 3, None, None))

    chunks = chunk_pages((page,), max_tokens=8)

    assert len(chunks) > 1
    assert all(chunk.page_index == 3 for chunk in chunks)
    assert all(chunk.token_count <= 8 for chunk in chunks)
    assert [chunk.sequence_number for chunk in chunks] == list(range(len(chunks)))
