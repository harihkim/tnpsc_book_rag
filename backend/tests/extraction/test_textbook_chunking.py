"""Native Docling parent-child textbook chunking tests."""

import re
from collections.abc import Callable
from dataclasses import replace
from typing import override

import pytest
from docling_core.transforms.chunker import DocChunk
from docling_core.transforms.chunker.doc_chunk import DocMeta
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.types.doc import (
    BoundingBox,
    DocItem,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
    TableCell,
    TableData,
)

from tnpsc_extraction.models import ChunkContentType, ContentUnitType, DisplayFormat
from tnpsc_extraction.textbook_chunking import (
    TextbookChunker,
    TextbookChunkingConfig,
    _native_text_fallback,
)

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
    caption = document.add_text(
        DocItemLabel.CAPTION,
        "Table 1.1 Common physical quantities",
        prov=_provenance(1, 145),
    )
    document.add_table(_table_data(), caption=caption, prov=_provenance(1, 150))
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
    assert all(unit.display_text.strip() for unit in result.content_units)
    assert all(chunk.display_text.strip() for chunk in result.chunks)
    assert all(chunk.token_count <= config.child_max_tokens for chunk in result.chunks)

    caption = next(
        unit
        for unit in result.content_units
        if unit.unit_type is ContentUnitType.CAPTION
        and "Common physical quantities" in unit.display_text
    )
    assert caption.display_text == "Table 1.1 Common physical quantities"

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
    table_children = [chunk for chunk in result.chunks if chunk.parent_local_id == table.local_id]
    assert table.display_format is DisplayFormat.MARKDOWN
    assert "| Quantity" in table.display_text
    assert table.structured_content is not None
    assert table.structured_content["num_rows"] == 5
    assert len(table_children) >= 2
    assert all(chunk.page_indexes == (0,) for chunk in table_children)
    assert all(chunk.content_type is ChunkContentType.TABLE for chunk in table_children)
    assert all("Meaning =" in chunk.display_text for chunk in table_children)
    assert all("Unit =" in chunk.display_text for chunk in table_children)


def test_short_table_resolves_generic_hybrid_metadata_after_serialization() -> None:
    """A table that needs no token split still resolves its canonical structured TableItem."""
    document = DoclingDocument.model_validate_json(_document().model_dump_json())
    config = _config(child_max_tokens=48)

    result = TextbookChunker(
        config,
        tokenizer=_TestTokenizer(max_tokens=config.child_max_tokens),
    ).chunk(document)

    table = next(unit for unit in result.content_units if unit.unit_type is ContentUnitType.TABLE)
    children = [chunk for chunk in result.chunks if chunk.parent_local_id == table.local_id]
    assert table.display_format is DisplayFormat.MARKDOWN
    assert table.structured_content is not None
    assert table.structured_content["num_rows"] == 5
    assert all(chunk.content_type is ChunkContentType.TABLE for chunk in children)


def test_blank_serialized_caption_recovers_its_native_text() -> None:
    document = DoclingDocument(name="blank-caption-fixture")
    caption = document.add_text(DocItemLabel.CAPTION, "Table 2 Deficiency Diseases")
    generic_item = DocItem(
        self_ref=caption.self_ref,
        label=caption.label,
        prov=caption.prov,
    )
    chunk = DocChunk(
        text="",
        meta=DocMeta(doc_items=[generic_item], headings=["Vitamins"]),
    )

    assert _native_text_fallback(document, chunk) == "Table 2 Deficiency Diseases"


def test_empty_formula_recovers_preserved_original_text() -> None:
    """A backend-extracted formula remains searchable when Docling's text field is empty."""
    document = DoclingDocument(name="formula-recovery-fixture")
    document.add_page(page_no=1, size=Size(width=200, height=300))
    document.add_heading("Ordering Numbers", level=1, prov=_provenance(1, 10))
    document.add_formula(
        "",
        orig="355 < 585 < 985 < 1245",
        prov=_provenance(1, 30),
    )
    config = _config()

    result = TextbookChunker(
        config,
        tokenizer=_TestTokenizer(max_tokens=config.child_max_tokens),
    ).chunk(document)

    assert len(result.content_units) == 1
    assert result.content_units[0].display_text == "355 < 585 < 985 < 1245"
    assert "formula-not-decoded" not in result.chunks[0].embedding_text
    assert result.chunks[0].provenance["formula_recovery"] == {
        "recovered_from_orig": 1,
        "unresolved": 0,
    }


def test_truly_empty_formula_is_retained_as_nonretrievable_diagnostic() -> None:
    """Irrecoverable source loss remains page-linked and cannot enter semantic search."""
    document = DoclingDocument(name="unresolved-formula-fixture")
    document.add_page(page_no=1, size=Size(width=200, height=300))
    document.add_heading("Ratio", level=1, prov=_provenance(1, 10))
    document.add_formula("", orig="", prov=_provenance(1, 30))
    config = _config()

    result = TextbookChunker(
        config,
        tokenizer=_TestTokenizer(max_tokens=config.child_max_tokens),
    ).chunk(document)

    assert len(result.content_units) == 1
    parent = result.content_units[0]
    assert parent.display_text == "Formula unavailable in extracted text; consult the source page."
    assert parent.retrieval_eligible is False
    assert parent.exclusion_reason == "unresolved_formula"
    assert result.chunks[0].page_indexes == (0,)
    assert result.chunks[0].provenance["formula_recovery"] == {
        "recovered_from_orig": 0,
        "unresolved": 1,
    }


def test_definition_statement_is_a_protected_single_parent_and_child() -> None:
    """Definition prose is recognized even when the section heading is generic."""
    document = DoclingDocument(name="implicit-definition-fixture")
    document.add_page(page_no=1, size=Size(width=200, height=300))
    document.add_heading("Measurement", level=1, prov=_provenance(1, 10))
    document.add_text(
        DocItemLabel.TEXT,
        "The distance between two points is known as length.",
        prov=_provenance(1, 30),
    )
    document.add_text(
        DocItemLabel.TEXT,
        "The comparison of an unknown quantity with a known quantity is called measurement.",
        prov=_provenance(1, 50),
    )
    config = _config(child_max_tokens=48)

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


def test_ordinary_short_siblings_merge_only_within_their_parent() -> None:
    """Small layout fragments become useful retrieval children without crossing sections."""
    document = DoclingDocument(name="short-fragments-fixture")
    document.add_page(page_no=1, size=Size(width=200, height=300))
    document.add_heading("Matter", level=1, prov=_provenance(1, 10))
    for index, text in enumerate(
        (
            "Matter occupies space and has mass.",
            "Solids have a fixed shape and volume.",
            "Liquids have a fixed volume but flow.",
        )
    ):
        document.add_text(
            DocItemLabel.TEXT,
            text,
            prov=_provenance(1, 30 + index * 20),
        )
    document.add_heading("Force", level=1, prov=_provenance(1, 100))
    document.add_text(
        DocItemLabel.TEXT,
        "A force is a push or pull.",
        prov=_provenance(1, 120),
    )
    config = _config(child_max_tokens=48)

    result = TextbookChunker(
        config,
        tokenizer=_TestTokenizer(max_tokens=config.child_max_tokens),
    ).chunk(document)

    matter_parent = next(unit for unit in result.content_units if unit.section_path == ("Matter",))
    matter_children = [
        chunk for chunk in result.chunks if chunk.parent_local_id == matter_parent.local_id
    ]
    assert len(matter_children) == 1
    assert len(matter_children[0].docling_refs) == 3
    assert "Solids have a fixed shape" in matter_children[0].display_text
    assert "Force" not in matter_children[0].display_text


def test_example_and_following_solution_heading_share_one_parent() -> None:
    """Textbook heading transitions must not detach a worked solution from its question."""
    document = DoclingDocument(name="example-solution-fixture")
    document.add_page(page_no=1, size=Size(width=200, height=300))
    document.add_heading("Example 1.1", level=1, prov=_provenance(1, 10))
    document.add_text(
        DocItemLabel.TEXT,
        "Simplify 24 + 2 \N{MULTIPLICATION SIGN} 8 ÷ 2 - 1.",
        prov=_provenance(1, 30),
    )
    document.add_heading("Solution", level=1, prov=_provenance(1, 50))
    document.add_text(
        DocItemLabel.TEXT,
        "Complete division first, then multiplication. The answer is 31.",
        prov=_provenance(1, 70),
    )
    config = _config(child_max_tokens=48)

    result = TextbookChunker(
        config,
        tokenizer=_TestTokenizer(max_tokens=config.child_max_tokens),
    ).chunk(document)

    examples = [
        unit for unit in result.content_units if unit.unit_type is ContentUnitType.SOLVED_EXAMPLE
    ]
    assert len(examples) == 1
    assert examples[0].section_path == ("Example 1.1",)
    assert "Simplify 24" in examples[0].display_text
    assert "The answer is 31" in examples[0].display_text
    children = [chunk for chunk in result.chunks if chunk.parent_local_id == examples[0].local_id]
    assert len(children) == 1
    assert children[0].section_path == examples[0].section_path


def test_control_characters_are_removed_and_replacement_text_is_excluded() -> None:
    """Known layout controls are harmless; irrecoverably corrupt text is not searchable."""
    document = DoclingDocument(name="corrupt-text-fixture")
    document.add_page(page_no=1, size=Size(width=200, height=300))
    document.add_heading("Summary", level=1, prov=_provenance(1, 10))
    document.add_text(
        DocItemLabel.TEXT,
        "\x99 Matter occupies space.",
        prov=_provenance(1, 30),
    )
    document.add_text(
        DocItemLabel.TEXT,
        "Click the bu�on in the digital activity.",
        prov=_provenance(1, 50),
    )
    config = _config(child_max_tokens=48)

    result = TextbookChunker(
        config,
        tokenizer=_TestTokenizer(max_tokens=config.child_max_tokens),
    ).chunk(document)

    assert all("\x99" not in unit.display_text for unit in result.content_units)
    corrupt = next(unit for unit in result.content_units if "bu�on" in unit.display_text)
    assert corrupt.retrieval_eligible is False
    assert corrupt.exclusion_reason == "replacement_character_corruption"


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
