#!/usr/bin/env python3
"""Extract one textbook into a checksummed, importable artifact package.

This script deliberately has no database or production-network dependency. It is intended for a
GPU notebook (for example, Google Colab) and produces a package that a future production importer
can verify before persisting it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def _configure_source_path() -> None:
    """Allow the script to run from a checkout without installing the backend application."""
    backend_root = Path(__file__).resolve().parents[1]
    source_root = backend_root / "src"
    import sys

    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))


def _metadata_text(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise SystemExit(f"--{field} must not be blank")
    if len(normalized) > maximum:
        raise SystemExit(f"--{field} must contain at most {maximum} characters")
    return normalized


def _book_metadata(arguments: argparse.Namespace) -> dict[str, object]:
    """Normalize the curriculum identity stored in every extraction manifest."""
    term_labels = {1: "Term I", 2: "Term II", 3: "Term III"}
    edition = arguments.edition or term_labels[arguments.term]
    return {
        "title": _metadata_text(arguments.title, field="title", maximum=500),
        "standard": arguments.standard,
        "subject": _metadata_text(arguments.subject, field="subject", maximum=200),
        "term": arguments.term,
        "language": arguments.language,
        "publisher": _metadata_text(arguments.publisher, field="publisher", maximum=300),
        "edition": _metadata_text(edition, field="edition", maximum=200),
    }


def _parse_args(
    *,
    default_tokenizer_identifier: str,
    default_tokenizer_revision: str,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Digital PDF with an accessible text layer")
    parser.add_argument("output", type=Path, help="New directory for the extraction package")
    parser.add_argument("--title", required=True, help="Human-facing textbook title")
    parser.add_argument(
        "--standard",
        type=int,
        choices=range(6, 11),
        required=True,
        help="Tamil Nadu State Board standard",
    )
    parser.add_argument("--subject", required=True, help="Textbook subject")
    parser.add_argument(
        "--term",
        type=int,
        choices=(1, 2, 3),
        required=True,
        help="Academic term number",
    )
    parser.add_argument(
        "--language",
        choices=("english",),
        default="english",
        help="Textbook language; English is the only supported MVP language",
    )
    parser.add_argument(
        "--publisher",
        default="Government of Tamil Nadu",
        help="Publisher name",
    )
    parser.add_argument(
        "--edition",
        help="Edition label; defaults to the selected term label when omitted",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
        help="Docling accelerator; auto prefers CUDA and falls back to CPU",
    )
    parser.add_argument(
        "--child-max-tokens",
        type=int,
        default=256,
        help="Contextualized retrieval-child limit; pilot candidates are 256 and 384",
    )
    parser.add_argument(
        "--parent-soft-tokens",
        type=int,
        default=800,
        help="Soft grouping target for ordinary parent content units",
    )
    parser.add_argument(
        "--parent-hard-tokens",
        type=int,
        default=1_200,
        help="Diagnostic hard target for semantic parent content units",
    )
    parser.add_argument(
        "--tokenizer-identifier",
        default=default_tokenizer_identifier,
        help="Hugging Face tokenizer/model identifier recorded in package v2",
    )
    parser.add_argument(
        "--tokenizer-revision",
        default=default_tokenizer_revision,
        help="Immutable Hugging Face revision; floating branches are not accepted",
    )
    parser.add_argument(
        "--no-table-structure",
        action="store_true",
        help="Disable table reconstruction only for a deliberate lightweight run",
    )
    parser.add_argument(
        "--include-source",
        action="store_true",
        help="Copy the original PDF into the package (off by default)",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        help="Optional deterministic .zip archive written after the package is complete",
    )
    return parser.parse_args()


def main() -> int:
    _configure_source_path()
    from docling_core.types.doc import DoclingDocument

    from tnpsc_extraction import (
        DoclingExtractor,
        ExtractionError,
        TextbookChunker,
        TextbookChunkingConfig,
    )
    from tnpsc_extraction.package_writer import (
        asset_payload,
        chunk_payload,
        chunking_manifest,
        content_unit_payload,
        files_manifest,
        json_dump,
        jsonl_dump,
        page_payload,
        sha256_file,
        write_deterministic_zip,
    )
    from tnpsc_extraction.textbook_chunking import (
        DEFAULT_TOKENIZER_IDENTIFIER,
        DEFAULT_TOKENIZER_REVISION,
    )

    arguments = _parse_args(
        default_tokenizer_identifier=DEFAULT_TOKENIZER_IDENTIFIER,
        default_tokenizer_revision=DEFAULT_TOKENIZER_REVISION,
    )
    source = arguments.pdf.expanduser().resolve()
    output = arguments.output.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"source PDF does not exist: {source}")
    if output.exists():
        raise SystemExit(f"output already exists; choose a new path: {output}")
    archive_target = (
        None if arguments.archive is None else arguments.archive.expanduser().resolve()
    )
    if archive_target is not None:
        if archive_target == output or output in archive_target.parents:
            raise SystemExit("--archive must be outside the extraction output directory")
        if archive_target.exists():
            raise SystemExit(f"archive already exists; choose a new path: {archive_target}")
    try:
        chunking_config = TextbookChunkingConfig(
            tokenizer_identifier=arguments.tokenizer_identifier,
            tokenizer_revision=arguments.tokenizer_revision,
            child_max_tokens=arguments.child_max_tokens,
            parent_soft_tokens=arguments.parent_soft_tokens,
            parent_hard_tokens=arguments.parent_hard_tokens,
        )
    except ValueError as error:
        raise SystemExit(f"invalid chunking configuration: {error}") from error

    try:
        import torch

        cuda_available = torch.cuda.is_available()
        torch_version = torch.__version__
        cuda_version = torch.version.cuda
        cuda_name = torch.cuda.get_device_name(0) if cuda_available else None
    except ImportError:
        cuda_available = False
        torch_version = None
        cuda_version = None
        cuda_name = None
    if arguments.device == "cuda" and not cuda_available:
        raise SystemExit("--device=cuda requested, but torch.cuda.is_available() is false")

    resolved_device = "cpu" if arguments.device == "cpu" else ("cuda" if cuda_available else "cpu")

    staging_parent = output.parent
    staging_parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.", dir=staging_parent) as temporary:
        staging = Path(temporary) / output.name
        staging.mkdir(mode=0o750)
        book_metadata = _book_metadata(arguments)
        extractor = DoclingExtractor(
            do_table_structure=not arguments.no_table_structure,
            accelerator_device=arguments.device,
            max_tokens=arguments.child_max_tokens,
        )
        try:
            bundle = extractor.extract(source, staging)
        except ExtractionError as error:
            raise SystemExit(f"extraction failed [{error.code}]: {error}") from error
        chunking_config = TextbookChunkingConfig(
            docling_version=bundle.docling_version,
            tokenizer_identifier=arguments.tokenizer_identifier,
            tokenizer_revision=arguments.tokenizer_revision,
            child_max_tokens=arguments.child_max_tokens,
            parent_soft_tokens=arguments.parent_soft_tokens,
            parent_hard_tokens=arguments.parent_hard_tokens,
        )
        document = DoclingDocument.load_from_json(bundle.docling_json_path)
        chunking_result = TextbookChunker(chunking_config).chunk(document)
        if not chunking_result.content_units or not chunking_result.chunks:
            raise SystemExit("chunking failed: document produced no retrieval content")

        jsonl_dump(staging / "pages.jsonl", [page_payload(page) for page in bundle.pages])
        jsonl_dump(
            staging / "assets.jsonl", [asset_payload(asset, staging) for asset in bundle.assets]
        )
        jsonl_dump(
            staging / "content_units.jsonl",
            [content_unit_payload(unit) for unit in chunking_result.content_units],
        )
        jsonl_dump(
            staging / "chunks.jsonl",
            [chunk_payload(chunk) for chunk in chunking_result.chunks],
        )
        if arguments.include_source:
            source_copy = staging / "source" / source.name
            source_copy.parent.mkdir(mode=0o750)
            shutil.copyfile(source, source_copy)

        manifest: dict[str, object] = {
            "manifest_version": 2,
            "created_at": datetime.now(UTC).isoformat(),
            "book": book_metadata,
            "source": {
                "filename": source.name,
                "sha256": sha256_file(source),
                "size_bytes": source.stat().st_size,
            },
            "runtime": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "torch": torch_version,
                "cuda_runtime": cuda_version,
                "cuda_available": cuda_available,
                "cuda_device": cuda_name,
            },
            "extraction": {
                "device_requested": arguments.device,
                "device_resolved": resolved_device,
                "do_table_structure": not arguments.no_table_structure,
                "generate_picture_images": True,
                "docling_version": bundle.docling_version,
                "config_fingerprint": bundle.config_fingerprint,
            },
            "chunking": chunking_manifest(chunking_config),
            "counts": {
                "pages": bundle.page_count,
                "pages_with_text": sum(bool(page.normalized_text) for page in bundle.pages),
                "content_units": len(chunking_result.content_units),
                "retrieval_eligible_content_units": sum(
                    unit.retrieval_eligible for unit in chunking_result.content_units
                ),
                "chunks": len(chunking_result.chunks),
                "assets": len(bundle.assets),
            },
            "files": files_manifest(staging),
        }
        json_dump(staging / "manifest.json", manifest)
        os.replace(staging, output)

    if archive_target is not None:
        write_deterministic_zip(output, archive_target)
    parent_type_counts: dict[str, int] = {}
    for unit in chunking_result.content_units:
        parent_type_counts[unit.unit_type.value] = (
            parent_type_counts.get(unit.unit_type.value, 0) + 1
        )
    token_counts = sorted(chunk.token_count for chunk in chunking_result.chunks)
    percentile_indexes = {
        "p50": round((len(token_counts) - 1) * 0.50),
        "p95": round((len(token_counts) - 1) * 0.95),
        "max": len(token_counts) - 1,
    }
    child_counts_by_parent: dict[str, int] = {}
    for chunk in chunking_result.chunks:
        child_counts_by_parent[chunk.parent_local_id] = (
            child_counts_by_parent.get(chunk.parent_local_id, 0) + 1
        )
    split_table_count = sum(
        unit.unit_type.value == "table" and child_counts_by_parent.get(unit.local_id, 0) > 1
        for unit in chunking_result.content_units
    )
    summary = {
        "manifest_version": 2,
        "output": str(output),
        "archive": None if archive_target is None else str(archive_target),
        "counts": manifest["counts"],
        "parent_types": parent_type_counts,
        "child_tokens": {name: token_counts[index] for name, index in percentile_indexes.items()},
        "split_table_count": split_table_count,
        "excluded_content_units": sum(
            not unit.retrieval_eligible for unit in chunking_result.content_units
        ),
        "page_warning_count": sum(len(page.warnings) for page in bundle.pages),
        "extraction_config_fingerprint": bundle.config_fingerprint,
        "chunking_config_fingerprint": chunking_result.config_fingerprint,
        "tokenizer_identifier": chunking_result.tokenizer_identifier,
        "tokenizer_revision": chunking_result.tokenizer_revision,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
