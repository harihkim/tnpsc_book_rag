"""Native Docling parent-child textbook chunking tests."""

import re
from collections.abc import Callable
from dataclasses import replace
from typing import override

import pytest
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.types.doc import (
    BoundingBox,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
    TableCell,
    TableData,
)

from tnpsc_extraction.models import ContentUnitType, DisplayFormat
from tnpsc_extraction.textbook_chunking import TextbookChunker, TextbookChunkingConfig

_TOKEN = re.compile(r"\S+")


class _TestTokenizer(BaseTokenizer):
    """Small deterministic tokenizer double compatible with Docling's splitter."""

    max_tokens: int

    @override
    def count_tokens(self, text: str) -> int:
        return len(_TOKEN.findall(text))

    @override
    def get_max_tokens(self) -> int:
        return self.max_tokens

    @override
    def get_tokenizer(self) -> Callable[[str], int]:
        return self.count_tokens


def _provenance(page_no: int, top: float) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=page_no,
        bbox=BoundingBox(l=10, t=top, r=190, b=top + 10),
        charspan=(0, 20),
    )


def _table_data() -> TableData:
    rows = [
        ("Quantity", "Meaning", "Unit"),
        ("Force", "push or pull", "newton"),
        ("Area", "surface covered", "square metre"),
        ("Pressure", "force per area", "pascal"),
        ("Mass", "amount of matter", "kilogram"),
    ]
    cells = [
        TableCell(
            start_row_offset_idx=row_index,
            end_row_offset_idx=row_index + 1,
            start_col_offset_idx=column_index,
            end_col_offset_idx=column_index + 1,
            text=text,
            column_header=row_index == 0,
        )
        for row_index, row in enumerate(rows)
        for column_index, text in enumerate(row)
    ]
    return TableData(table_cells=cells, num_rows=len(rows), num_cols=len(rows[0]))


def _document() -> DoclingDocument:
    document = DoclingDocument(name="science-term-one-fixture")
    document.add_page(page_no=1, size=Size(width=200, height=300))
    document.add_heading("Force and Pressure", level=1, prov=_provenance(1, 10))
    document.add_heading("Definition", level=2, prov=_provenance(1, 30))
    document.add_text(
        DocItemLabel.TEXT,
        "Pressure is force acting per unit area.",
        prov=_provenance(1, 50),
    )
    document.add_heading("Worked Example 1", level=2, prov=_provenance(1, 70))
    document.add_text(
        DocItemLabel.TEXT,
        "Question: Find the pressure when force is ten newtons and area is two square metres.",
        prov=_provenance(1, 90),
    )
    document.add_text(
        DocItemLabel.TEXT,
        "Solution: Divide force by area. The pressure is five pascals.",
        prov=_provenance(1, 110),
    )
    document.add_heading("Measurements", level=2, prov=_provenance(1, 130))
    document.add_table(_table_data(), prov=_provenance(1, 150))
    document.add_text(
        DocItemLabel.PAGE_FOOTER,
        "science-term-1.indd 42",
        prov=_provenance(1, 280),
    )
    return document


def _config(*, child_max_tokens: int = 24) -> TextbookChunkingConfig:
    return TextbookChunkingConfig(
        docling_version="fixture-docling",
        tokenizer_revision="fixture-tokenizer-revision",
        child_max_tokens=child_max_tokens,
        parent_soft_tokens=60,
        parent_hard_tokens=100,
    )


def test_config_fingerprint_is_canonical_and_complete() -> None:
    """Equal configs match while a retrieval-affecting change creates a new identity."""
    config = _config()

    assert config.fingerprint == _config().fingerprint
    assert config.fingerprint != replace(config, child_max_tokens=32).fingerprint
    assert config.manifest_values()["tokenizer_revision"] == "fixture-tokenizer-revision"


@pytest.mark.parametrize("child_max_tokens", [0, 513])
def test_config_rejects_values_outside_the_embedding_model_limit(
    child_max_tokens: int,
) -> None:
    with pytest.raises(ValueError, match="child_max_tokens"):
        _config(child_max_tokens=child_max_tokens)


def test_native_chunking_preserves_semantic_parents_and_table_structure() -> None:
    """Definitions, worked examples, and complete tables remain expandable parents."""
    config = _config()
    result = TextbookChunker(
        config,
        tokenizer=_TestTokenizer(max_tokens=config.child_max_tokens),
    ).chunk(_document())

    assert [unit.local_id for unit in result.content_units] == [
        f"U{index:06d}" for index in range(len(result.content_units))
    ]
    assert [chunk.local_id for chunk in result.chunks] == [
        f"C{index:06d}" for index in range(len(result.chunks))
    ]
    assert all(chunk.token_count <= config.child_max_tokens for chunk in result.chunks)

    definition = next(
        unit for unit in result.content_units if unit.unit_type is ContentUnitType.DEFINITION
    )
    definition_children = [
        chunk for chunk in result.chunks if chunk.parent_local_id == definition.local_id
    ]
    assert len(definition_children) == 1
    assert definition.section_path == ("Force and Pressure", "Definition")
    assert "Force and Pressure" in definition_children[0].embedding_text

    example = next(
        unit for unit in result.content_units if unit.unit_type is ContentUnitType.SOLVED_EXAMPLE
    )
    example_children = [
        chunk for chunk in result.chunks if chunk.parent_local_id == example.local_id
    ]
    assert len(example_children) >= 2
    assert "Question:" in example.display_text
    assert "Solution:" in example.display_text

    table = next(unit for unit in result.content_units if unit.unit_type is ContentUnitType.TABLE)
    table_children = [
        chunk for chunk in result.chunks if chunk.parent_local_id == table.local_id
    ]
    assert table.display_format is DisplayFormat.MARKDOWN
    assert "| Quantity" in table.display_text
    assert table.structured_content is not None
    assert table.structured_content["num_rows"] == 5
    assert len(table_children) >= 2
    assert all(chunk.page_indexes == (0,) for chunk in table_children)
    assert all("Meaning =" in chunk.display_text for chunk in table_children)
    assert all("Unit =" in chunk.display_text for chunk in table_children)


def test_adjacent_definitions_under_a_generic_heading_remain_separate() -> None:
    """A glossary-like section must not collapse multiple definitions into one parent."""
    document = DoclingDocument(name="definitions-fixture")
    document.add_page(page_no=1, size=Size(width=200, height=300))
    document.add_heading("Key Terms", level=1, prov=_provenance(1, 10))
    document.add_text(
        DocItemLabel.TEXT,
        "Definition: Force is a push or pull.",
        prov=_provenance(1, 30),
    )
    document.add_text(
        DocItemLabel.TEXT,
        "Definition: Pressure is force per unit area.",
        prov=_provenance(1, 50),
    )
    config = _config()

    result = TextbookChunker(
        config,
        tokenizer=_TestTokenizer(max_tokens=config.child_max_tokens),
    ).chunk(document)

    definitions = [
        unit for unit in result.content_units if unit.unit_type is ContentUnitType.DEFINITION
    ]
    assert len(definitions) == 2
    assert all(
        sum(chunk.parent_local_id == unit.local_id for chunk in result.chunks) == 1
        for unit in definitions
    )


def test_chunking_is_deterministic_and_marks_explicit_footer_noise() -> None:
    config = _config()
    chunker = TextbookChunker(
        config,
        tokenizer=_TestTokenizer(max_tokens=config.child_max_tokens),
    )

    first = chunker.chunk(_document())
    second = chunker.chunk(_document())

    assert first == second
    excluded = [unit for unit in first.content_units if not unit.retrieval_eligible]
    assert len(excluded) == 1
    assert excluded[0].exclusion_reason in {
        "explicit_page_margin_label",
        "indd_export_marker",
    }
