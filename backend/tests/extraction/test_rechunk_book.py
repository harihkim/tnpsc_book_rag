"""End-to-end tests for package-v2 rechunking without Docling conversion."""

import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from runpy import run_path
from typing import override
from zipfile import ZipFile

import pytest
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.types.doc import (
    BoundingBox,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
)

import tnpsc_extraction.textbook_chunking as chunking_module
from tnpsc_extraction.models import ExtractedBlock, ExtractedPage, TextbookChunkingResult
from tnpsc_extraction.package import verify_extraction_package
from tnpsc_extraction.package_writer import (
    chunk_payload,
    chunking_manifest,
    content_unit_payload,
    files_manifest,
    json_dump,
    jsonl_dump,
    page_payload,
    write_deterministic_zip,
)
from tnpsc_extraction.textbook_chunking import TextbookChunker, TextbookChunkingConfig

_TOKEN = re.compile(r"\S+")


class _TestTokenizer(BaseTokenizer):
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


class _OfflineTestChunker:
    """Inject the deterministic tokenizer while exercising the real shared chunker."""

    def __init__(self, config: TextbookChunkingConfig) -> None:
        self._delegate = TextbookChunker(
            config,
            tokenizer=_TestTokenizer(max_tokens=config.child_max_tokens),
        )

    def chunk(self, document: DoclingDocument) -> TextbookChunkingResult:
        return self._delegate.chunk(document)


def _provenance() -> ProvenanceItem:
    return ProvenanceItem(
        page_no=1,
        bbox=BoundingBox(l=10, t=10, r=190, b=30),
        charspan=(0, 80),
    )


def _source_archive(root: Path) -> Path:
    package_root = root / "source-package"
    package_root.mkdir()
    document = DoclingDocument(name="rechunk-fixture")
    document.add_page(page_no=1, size=Size(width=200, height=300))
    document.add_heading("Matter", level=1, prov=_provenance())
    text = "Matter occupies space and has mass. Solids, liquids, and gases are common states."
    document.add_text(DocItemLabel.TEXT, text, prov=_provenance())
    document.save_as_json(package_root / "docling.json")
    page = ExtractedPage(
        pdf_page_index=0,
        width=200,
        height=300,
        raw_text=text,
        normalized_text=text,
        blocks=(ExtractedBlock(text, "prose", 0, None, (0, len(text))),),
        warnings=(),
    )
    jsonl_dump(package_root / "pages.jsonl", [page_payload(page)])
    jsonl_dump(package_root / "assets.jsonl", [])

    config = TextbookChunkingConfig(
        docling_version="2.112.0",
        tokenizer_revision="fixture-revision",
        child_max_tokens=16,
        parent_soft_tokens=32,
        parent_hard_tokens=64,
    )
    result = TextbookChunker(
        config,
        tokenizer=_TestTokenizer(max_tokens=config.child_max_tokens),
    ).chunk(document)
    jsonl_dump(
        package_root / "content_units.jsonl",
        (content_unit_payload(unit) for unit in result.content_units),
    )
    jsonl_dump(
        package_root / "chunks.jsonl",
        (chunk_payload(chunk) for chunk in result.chunks),
    )
    manifest: dict[str, object] = {
        "manifest_version": 2,
        "created_at": datetime.now(UTC).isoformat(),
        "book": {
            "title": "Standard 6 Science",
            "standard": 6,
            "subject": "Science",
            "term": 1,
            "language": "english",
            "publisher": "Government of Tamil Nadu",
            "edition": "Term I",
        },
        "source": {"filename": "science.pdf", "sha256": "b" * 64, "size_bytes": 10},
        "runtime": {
            "python": "3.13",
            "platform": "fixture-linux",
            "torch": None,
            "cuda_runtime": None,
            "cuda_available": False,
            "cuda_device": None,
        },
        "extraction": {
            "device_requested": "cpu",
            "device_resolved": "cpu",
            "do_table_structure": True,
            "generate_picture_images": True,
            "docling_version": "2.112.0",
            "config_fingerprint": "c" * 64,
        },
        "chunking": chunking_manifest(config),
        "counts": {
            "pages": 1,
            "pages_with_text": 1,
            "content_units": len(result.content_units),
            "retrieval_eligible_content_units": len(result.content_units),
            "chunks": len(result.chunks),
            "assets": 0,
        },
        "files": files_manifest(package_root),
    }
    json_dump(package_root / "manifest.json", manifest)
    archive = root / "source-v2.zip"
    write_deterministic_zip(package_root, archive)
    verify_extraction_package(archive)
    return archive


def test_rechunk_reuses_verified_docling_and_emits_a_new_verified_variant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_archive = _source_archive(tmp_path)
    output = tmp_path / "variant-24"
    output_archive = tmp_path / "variant-24.zip"
    script_path = Path(__file__).parents[2] / "scripts" / "rechunk_book.py"
    namespace = run_path(str(script_path))
    monkeypatch.setattr(chunking_module, "TextbookChunker", _OfflineTestChunker)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rechunk_book.py",
            str(source_archive),
            str(output),
            "--child-max-tokens",
            "24",
            "--archive",
            str(output_archive),
        ],
    )

    assert namespace["main"]() == 0

    source = verify_extraction_package(source_archive)
    variant = verify_extraction_package(output_archive)
    assert variant.chunking.child_max_tokens == 24
    assert variant.chunking.config_fingerprint != source.chunking.config_fingerprint
    assert variant.extraction_config_fingerprint == source.extraction_config_fingerprint
    with ZipFile(source_archive) as source_zip, ZipFile(output_archive) as variant_zip:
        for path in ("docling.json", "pages.jsonl", "assets.jsonl"):
            assert variant_zip.read(path) == source_zip.read(path)
