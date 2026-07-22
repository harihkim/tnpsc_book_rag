"""Tests for the offline extraction package-v2 verification boundary."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from tnpsc_book_rag.pdf_extraction.package import (
    ExtractionPackageError,
    verify_extraction_package,
)
from tnpsc_extraction.textbook_chunking import TextbookChunkingConfig

type PackageMutator = Callable[[dict[str, Any], dict[str, bytes]], None]


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _json_sha256(value: dict[str, object]) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return _text_sha256(payload)


def _jsonl(*records: dict[str, object]) -> bytes:
    return b"".join(
        (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode()
        for record in records
    )


def _parent(
    *,
    unit_type: str = "prose",
    display_text: str = "Matter is anything that has mass.",
    display_format: str = "plain_text",
    structured_content: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "local_id": "U000000",
        "sequence_number": 0,
        "unit_type": unit_type,
        "display_text": display_text,
        "display_format": display_format,
        "structured_content": structured_content,
        "section_path": ["Matter"],
        "retrieval_eligible": True,
        "exclusion_reason": None,
        "content_sha256": _json_sha256(
            {
                "display_format": display_format,
                "display_text": display_text,
                "structured_content": structured_content,
            }
        ),
        "page_indexes": [0],
        "docling_refs": ["#/texts/0"],
        "provenance": {"children": []},
    }


def _chunk(
    *,
    sequence_number: int = 0,
    display_text: str = "Matter is anything that has mass.",
    embedding_text: str = "Matter\nMatter is anything that has mass.",
    content_type: str = "prose",
    token_count: int = 8,
) -> dict[str, object]:
    return {
        "local_id": f"C{sequence_number:06d}",
        "parent_local_id": "U000000",
        "sequence_number": sequence_number,
        "display_text": display_text,
        "display_format": "plain_text",
        "embedding_text": embedding_text,
        "chapter_title": "Matter",
        "section_path": ["Matter"],
        "content_type": content_type,
        "token_count": token_count,
        "display_sha256": _text_sha256(display_text),
        "embedding_sha256": _text_sha256(embedding_text),
        "page_indexes": [0],
        "docling_refs": ["#/texts/0"],
        "provenance": {"doc_items": []},
    }


def _base_package() -> tuple[dict[str, Any], dict[str, bytes]]:
    image = b"png-bytes"
    image_checksum = hashlib.sha256(image).hexdigest()
    config = TextbookChunkingConfig(
        docling_version="2.112.0",
        tokenizer_revision="fixture-tokenizer-revision",
        child_max_tokens=16,
        parent_soft_tokens=32,
        parent_hard_tokens=64,
    )
    payloads = {
        "assets.jsonl": _jsonl(
            {
                "coordinate_origin": None,
                "bounding_box": None,
                "caption": None,
                "height": 1,
                "media_type": "image/png",
                "ordinal": 0,
                "page_index": 0,
                "path": "images/one.png",
                "provenance": {},
                "sha256": image_checksum,
                "source_reference": "#/pictures/0",
                "width": 1,
            }
        ),
        "chunks.jsonl": _jsonl(_chunk()),
        "content_units.jsonl": _jsonl(_parent()),
        "docling.json": json.dumps(
            {"texts": [{"self_ref": "#/texts/0", "text": "Matter"}]}
        ).encode(),
        "images/one.png": image,
        "pages.jsonl": _jsonl(
            {
                "blocks": [],
                "height": 792.0,
                "pdf_page_index": 0,
                "raw_text": "Matter",
                "normalized_text": "Matter",
                "warnings": [],
                "width": 612.0,
            }
        ),
    }
    manifest: dict[str, Any] = {
        "manifest_version": 2,
        "created_at": "2026-07-18T10:00:00+00:00",
        "book": {
            "title": "Tamil Nadu State Board Standard 6 Science",
            "standard": 6,
            "subject": "Science",
            "term": 1,
            "language": "english",
            "publisher": "Government of Tamil Nadu",
            "edition": "Term I",
        },
        "source": {
            "filename": "science.pdf",
            "sha256": "b" * 64,
            "size_bytes": 10,
        },
        "extraction": {
            "device_requested": "cpu",
            "device_resolved": "cpu",
            "do_table_structure": True,
            "generate_picture_images": True,
            "docling_version": "2.112.0",
            "config_fingerprint": "c" * 64,
        },
        "runtime": {
            "python": "3.13.5",
            "platform": "fixture-linux",
            "torch": None,
            "cuda_runtime": None,
            "cuda_available": False,
            "cuda_device": None,
        },
        "chunking": {
            "content_unit_schema_version": 1,
            "chunk_schema_version": 1,
            **config.manifest_values(),
            "config_fingerprint": config.fingerprint,
        },
        "counts": {
            "pages": 1,
            "pages_with_text": 1,
            "content_units": 1,
            "retrieval_eligible_content_units": 1,
            "chunks": 1,
            "assets": 1,
        },
    }
    return manifest, payloads


def _write_package(
    path: Path,
    *,
    mutate: PackageMutator | None = None,
    tamper_payload: str | None = None,
    unlisted_entry: str | None = None,
) -> None:
    manifest, payloads = _base_package()
    if mutate is not None:
        mutate(manifest, payloads)
    manifest["files"] = [
        {
            "path": name,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for name, data in sorted(payloads.items())
    ]
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest).encode())
        for name, data in payloads.items():
            archive.writestr(name, b"tampered" if name == tamper_payload else data)
        if unlisted_entry is not None:
            archive.writestr(unlisted_entry, b"unexpected")


def _replace_record(payloads: dict[str, bytes], path: str, record: dict[str, object]) -> None:
    payloads[path] = _jsonl(record)


def test_verify_v2_accepts_parent_child_metadata_and_payloads(tmp_path: Path) -> None:
    package_path = tmp_path / "science-v2.zip"
    _write_package(package_path)

    verified = verify_extraction_package(package_path)

    assert verified.book.standard == 6
    assert verified.page_count == 1
    assert verified.content_unit_count == 1
    assert verified.chunk_count == 1
    assert verified.asset_count == 1
    assert verified.chunking.child_max_tokens == 16
    assert verified.chunking.tokenizer_revision == "fixture-tokenizer-revision"


def test_verify_v2_rejects_v1_with_reextract_guidance(tmp_path: Path) -> None:
    package_path = tmp_path / "science-v1.zip"

    def use_v1(manifest: dict[str, Any], _: dict[str, bytes]) -> None:
        manifest["manifest_version"] = 1

    _write_package(package_path, mutate=use_v1)

    with pytest.raises(ExtractionPackageError, match="diagnostic-only; re-extract"):
        verify_extraction_package(package_path)


def test_verify_v2_rejects_payload_checksum_mismatch(tmp_path: Path) -> None:
    package_path = tmp_path / "tampered.zip"
    _write_package(package_path, tamper_payload="chunks.jsonl")

    with pytest.raises(ExtractionPackageError, match=r"payload (size|checksum) mismatch"):
        verify_extraction_package(package_path)


def test_verify_v2_rejects_asset_metadata_mismatch_and_orphan_images(tmp_path: Path) -> None:
    checksum_path = tmp_path / "asset-checksum.zip"

    def change_asset_checksum(_: dict[str, Any], payloads: dict[str, bytes]) -> None:
        asset = json.loads(payloads["assets.jsonl"])
        asset["sha256"] = "d" * 64
        _replace_record(payloads, "assets.jsonl", asset)

    _write_package(checksum_path, mutate=change_asset_checksum)
    with pytest.raises(ExtractionPackageError, match="does not match its image payload"):
        verify_extraction_package(checksum_path)

    orphan_path = tmp_path / "orphan-image.zip"

    def add_orphan_image(_: dict[str, Any], payloads: dict[str, bytes]) -> None:
        payloads["images/orphan.png"] = b"orphan"

    _write_package(orphan_path, mutate=add_orphan_image)
    with pytest.raises(ExtractionPackageError, match="image without asset metadata"):
        verify_extraction_package(orphan_path)


def test_verify_v2_recomputes_chunking_fingerprint(tmp_path: Path) -> None:
    package_path = tmp_path / "bad-fingerprint.zip"

    def change_limit(manifest: dict[str, Any], _: dict[str, bytes]) -> None:
        manifest["chunking"]["child_max_tokens"] = 15

    _write_package(package_path, mutate=change_limit)

    with pytest.raises(ExtractionPackageError, match="fingerprint does not match"):
        verify_extraction_package(package_path)


def test_verify_v2_rejects_unknown_parent_and_docling_references(tmp_path: Path) -> None:
    parent_path = tmp_path / "unknown-parent.zip"

    def unknown_parent(_: dict[str, Any], payloads: dict[str, bytes]) -> None:
        record = _chunk()
        record["parent_local_id"] = "U999999"
        _replace_record(payloads, "chunks.jsonl", record)

    _write_package(parent_path, mutate=unknown_parent)
    with pytest.raises(ExtractionPackageError, match="unknown parent"):
        verify_extraction_package(parent_path)

    reference_path = tmp_path / "unknown-reference.zip"

    def unknown_reference(_: dict[str, Any], payloads: dict[str, bytes]) -> None:
        record = _parent()
        record["docling_refs"] = ["#/texts/999"]
        _replace_record(payloads, "content_units.jsonl", record)

    _write_package(reference_path, mutate=unknown_reference)
    with pytest.raises(ExtractionPackageError, match="known Docling references"):
        verify_extraction_package(reference_path)


def test_verify_v2_rejects_checksum_and_token_limit_mismatches(tmp_path: Path) -> None:
    checksum_path = tmp_path / "bad-content-checksum.zip"

    def bad_checksum(_: dict[str, Any], payloads: dict[str, bytes]) -> None:
        record = _parent()
        record["display_text"] = "Changed without changing the content checksum."
        _replace_record(payloads, "content_units.jsonl", record)

    _write_package(checksum_path, mutate=bad_checksum)
    with pytest.raises(ExtractionPackageError, match="does not match parent content"):
        verify_extraction_package(checksum_path)

    token_path = tmp_path / "oversized-child.zip"

    def oversized_child(_: dict[str, Any], payloads: dict[str, bytes]) -> None:
        _replace_record(payloads, "chunks.jsonl", _chunk(token_count=17))

    _write_package(token_path, mutate=oversized_child)
    with pytest.raises(ExtractionPackageError, match="token_count exceeds"):
        verify_extraction_package(token_path)


def test_verify_v2_rejects_split_table_without_repeated_headers(tmp_path: Path) -> None:
    package_path = tmp_path / "table-without-header.zip"

    def split_table(manifest: dict[str, Any], payloads: dict[str, bytes]) -> None:
        structured_content: dict[str, object] = {
            "num_rows": 3,
            "num_cols": 3,
            "table_cells": [
                {
                    "column_header": True,
                    "start_col_offset_idx": column,
                    "text": text,
                }
                for column, text in enumerate(("Quantity", "Meaning", "Unit"))
            ],
        }
        parent = _parent(
            unit_type="table",
            display_text="| Quantity | Meaning | Unit |",
            display_format="markdown",
            structured_content=structured_content,
        )
        first = _chunk(
            display_text="Force, Meaning = push, Unit = newton",
            embedding_text="Matter\nForce, Meaning = push, Unit = newton",
            content_type="table",
        )
        second = _chunk(
            sequence_number=1,
            display_text="Area is measured in square metres",
            embedding_text="Matter\nArea is measured in square metres",
            content_type="table",
        )
        payloads["content_units.jsonl"] = _jsonl(parent)
        payloads["chunks.jsonl"] = _jsonl(first, second)
        manifest["counts"]["chunks"] = 2

    _write_package(package_path, mutate=split_table)

    with pytest.raises(ExtractionPackageError, match="does not repeat its headers"):
        verify_extraction_package(package_path)


def test_verify_v2_accepts_split_table_that_has_no_native_headers(tmp_path: Path) -> None:
    """Puzzles and layout grids can be tables without a semantic header to repeat."""
    package_path = tmp_path / "headerless-grid.zip"

    def split_headerless_grid(manifest: dict[str, Any], payloads: dict[str, bytes]) -> None:
        structured_content: dict[str, object] = {
            "num_rows": 2,
            "num_cols": 2,
            "table_cells": [
                {
                    "column_header": False,
                    "start_col_offset_idx": column,
                    "text": text,
                }
                for column, text in enumerate(("A", "B"))
            ],
        }
        parent = _parent(
            unit_type="table",
            display_text="| A | B |",
            display_format="markdown",
            structured_content=structured_content,
        )
        first = _chunk(
            display_text="A, 1 = C",
            embedding_text="Matter\nA, 1 = C",
            content_type="table",
        )
        second = _chunk(
            sequence_number=1,
            display_text="B, 1 = D",
            embedding_text="Matter\nB, 1 = D",
            content_type="table",
        )
        payloads["content_units.jsonl"] = _jsonl(parent)
        payloads["chunks.jsonl"] = _jsonl(first, second)
        manifest["counts"]["chunks"] = 2

    _write_package(package_path, mutate=split_headerless_grid)

    verified = verify_extraction_package(package_path)

    assert verified.chunk_count == 2


def test_verify_v2_rejects_unlisted_zip_payload(tmp_path: Path) -> None:
    package_path = tmp_path / "unlisted.zip"
    _write_package(package_path, unlisted_entry="notes/private.txt")

    with pytest.raises(ExtractionPackageError, match="unlisted payloads"):
        verify_extraction_package(package_path)
