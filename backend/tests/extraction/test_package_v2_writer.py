"""Package-v2 serialization helpers shared by the offline extraction script."""

import hashlib
from collections.abc import Callable
from pathlib import Path
from runpy import run_path
from typing import Any, cast

from tnpsc_extraction.models import (
    ChunkContentType,
    ContentUnitType,
    DisplayFormat,
    ExtractedContentUnit,
    ExtractedRetrievalChunk,
)
from tnpsc_extraction.textbook_chunking import TextbookChunkingConfig


def _script_functions() -> dict[str, Callable[..., dict[str, object]]]:
    script_path = Path(__file__).parents[2] / "scripts" / "extract_book.py"
    namespace = run_path(str(script_path))
    names = ("_chunking_manifest", "_content_unit_payload", "_chunk_payload")
    return {
        name: cast(Callable[..., dict[str, object]], namespace[name])
        for name in names
    }


def test_chunking_manifest_contains_the_complete_fingerprinted_configuration() -> None:
    config = TextbookChunkingConfig(
        docling_version="fixture-docling",
        tokenizer_revision="fixture-revision",
    )

    manifest = _script_functions()["_chunking_manifest"](config)

    assert manifest["content_unit_schema_version"] == 1
    assert manifest["chunk_schema_version"] == 1
    assert manifest["tokenizer_identifier"] == "BAAI/bge-small-en-v1.5"
    assert manifest["tokenizer_revision"] == "fixture-revision"
    assert manifest["config_fingerprint"] == config.fingerprint


def test_parent_and_child_payloads_make_enums_and_references_explicit() -> None:
    functions = _script_functions()
    parent = ExtractedContentUnit(
        local_id="U000000",
        sequence_number=0,
        unit_type=ContentUnitType.DEFINITION,
        display_text="Pressure is force per unit area.",
        display_format=DisplayFormat.PLAIN_TEXT,
        structured_content=None,
        section_path=("Pressure", "Definition"),
        retrieval_eligible=True,
        exclusion_reason=None,
        content_sha256="a" * 64,
        page_indexes=(4, 5),
        docling_refs=("#/texts/8",),
        provenance={},
    )
    embedding_text = "Pressure\nDefinition\nPressure is force per unit area."
    child = ExtractedRetrievalChunk(
        local_id="C000000",
        parent_local_id=parent.local_id,
        sequence_number=0,
        display_text=parent.display_text,
        display_format=DisplayFormat.PLAIN_TEXT,
        embedding_text=embedding_text,
        chapter_title="Pressure",
        section_path=parent.section_path,
        content_type=ChunkContentType.PROSE,
        token_count=10,
        display_sha256=hashlib.sha256(parent.display_text.encode()).hexdigest(),
        embedding_sha256=hashlib.sha256(embedding_text.encode()).hexdigest(),
        page_indexes=parent.page_indexes,
        docling_refs=parent.docling_refs,
        provenance={},
    )

    parent_payload = functions["_content_unit_payload"](cast(Any, parent))
    child_payload = functions["_chunk_payload"](cast(Any, child))

    assert parent_payload["unit_type"] == "definition"
    assert parent_payload["display_format"] == "plain_text"
    assert parent_payload["page_indexes"] == [4, 5]
    assert parent_payload["docling_refs"] == ["#/texts/8"]
    assert child_payload["parent_local_id"] == "U000000"
    assert child_payload["content_type"] == "prose"
    assert child_payload["embedding_sha256"] == child.embedding_sha256
