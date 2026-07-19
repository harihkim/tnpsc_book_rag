#!/usr/bin/env python3
"""Create a new package-v2 chunk variant without running Docling conversion again."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast
from zipfile import ZipFile

if TYPE_CHECKING:
    from tnpsc_extraction.package import PackageFile, VerifiedExtractionPackage
    from tnpsc_extraction.textbook_chunking import TextbookChunkingConfig


def _configure_source_path() -> None:
    """Allow the script to run from a checkout without installing the backend application."""
    backend_root = Path(__file__).resolve().parents[1]
    source_root = backend_root / "src"
    import sys

    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_archive", type=Path, help="Verified package-v2 ZIP to reuse")
    parser.add_argument("output", type=Path, help="New directory for the rechunked package")
    parser.add_argument(
        "--child-max-tokens",
        type=int,
        required=True,
        help="New contextualized child limit, normally the alternate 256/384 pilot value",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        required=True,
        help="New verified package-v2 ZIP; must be outside the output directory",
    )
    return parser.parse_args()


def main() -> int:
    _configure_source_path()
    from docling_core.types.doc import DoclingDocument

    from tnpsc_extraction.package import verify_extraction_package
    from tnpsc_extraction.package_writer import (
        chunk_payload,
        chunking_manifest,
        content_unit_payload,
        files_manifest,
        json_dump,
        jsonl_dump,
        write_deterministic_zip,
    )
    from tnpsc_extraction.textbook_chunking import (
        TEXTBOOK_CHUNKER_VERSION,
        TextbookChunker,
        TextbookChunkingConfig,
    )

    arguments = _parse_args()
    source_archive = arguments.source_archive.expanduser().resolve()
    output = arguments.output.expanduser().resolve()
    output_archive = arguments.archive.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"output already exists; choose a new path: {output}")
    if output_archive.exists():
        raise SystemExit(f"archive already exists; choose a new path: {output_archive}")
    if output_archive == source_archive:
        raise SystemExit("--archive must not replace the source package")
    if output_archive == output or output in output_archive.parents:
        raise SystemExit("--archive must be outside the rechunked output directory")

    verified = verify_extraction_package(source_archive)
    source_config = _source_config(verified, TextbookChunkingConfig)
    if source_config.implementation_version != TEXTBOOK_CHUNKER_VERSION:
        raise SystemExit("source package uses a different chunker implementation version")
    if arguments.child_max_tokens == source_config.child_max_tokens:
        raise SystemExit("--child-max-tokens must differ from the source package")
    try:
        target_config = replace(source_config, child_max_tokens=arguments.child_max_tokens)
    except ValueError as error:
        raise SystemExit(f"invalid rechunk configuration: {error}") from error

    output.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    output_archive.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.", dir=output.parent) as temporary:
        temporary_root = Path(temporary)
        staging = temporary_root / output.name
        staging.mkdir(mode=0o750)
        manifest = _materialize_reusable_payloads(source_archive, verified.files, staging)
        document = DoclingDocument.load_from_json(staging / "docling.json")
        result = TextbookChunker(target_config).chunk(document)
        if not result.content_units or not result.chunks:
            raise SystemExit("rechunking failed: document produced no retrieval content")

        jsonl_dump(
            staging / "content_units.jsonl",
            (content_unit_payload(unit) for unit in result.content_units),
        )
        jsonl_dump(
            staging / "chunks.jsonl",
            (chunk_payload(chunk) for chunk in result.chunks),
        )
        counts = _mapping(manifest.get("counts"), "manifest.counts")
        counts["content_units"] = len(result.content_units)
        counts["retrieval_eligible_content_units"] = sum(
            unit.retrieval_eligible for unit in result.content_units
        )
        counts["chunks"] = len(result.chunks)
        manifest["created_at"] = datetime.now(UTC).isoformat()
        manifest["chunking"] = chunking_manifest(target_config)
        manifest["files"] = files_manifest(staging)
        json_dump(staging / "manifest.json", manifest)

        staged_archive = temporary_root / "rechunked.zip"
        write_deterministic_zip(staging, staged_archive)
        staged_verification = verify_extraction_package(staged_archive)
        if staged_verification.chunking.config_fingerprint != target_config.fingerprint:
            raise SystemExit("rechunked archive verification returned the wrong fingerprint")

        os.replace(staging, output)
        os.replace(staged_archive, output_archive)

    summary = {
        "manifest_version": 2,
        "source_archive": str(source_archive),
        "output": str(output),
        "archive": str(output_archive),
        "source_child_max_tokens": source_config.child_max_tokens,
        "child_max_tokens": target_config.child_max_tokens,
        "content_units": len(result.content_units),
        "chunks": len(result.chunks),
        "source_chunking_config_fingerprint": source_config.fingerprint,
        "chunking_config_fingerprint": target_config.fingerprint,
        "docling_reused": True,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _source_config(
    verified: VerifiedExtractionPackage,
    config_type: type[TextbookChunkingConfig],
) -> TextbookChunkingConfig:
    """Reconstruct and validate the source package's resolved runtime configuration."""
    current = config_type(
        docling_version=verified.docling_version,
        tokenizer_identifier=verified.chunking.tokenizer_identifier,
        tokenizer_revision=verified.chunking.tokenizer_revision,
        child_max_tokens=verified.chunking.child_max_tokens,
        parent_soft_tokens=verified.chunking.parent_soft_tokens,
        parent_hard_tokens=verified.chunking.parent_hard_tokens,
    )
    source_values = {
        "docling_version": verified.docling_version,
        "implementation_version": verified.chunking.implementation_version,
        "tokenizer_identifier": verified.chunking.tokenizer_identifier,
        "tokenizer_revision": verified.chunking.tokenizer_revision,
        "child_max_tokens": verified.chunking.child_max_tokens,
        "parent_soft_tokens": verified.chunking.parent_soft_tokens,
        "parent_hard_tokens": verified.chunking.parent_hard_tokens,
        "merge_peers": verified.chunking.merge_peers,
        "repeat_table_header": verified.chunking.repeat_table_header,
        "omit_header_on_overflow": verified.chunking.omit_header_on_overflow,
        "display_serializer_version": verified.chunking.display_serializer_version,
        "table_serializer_version": verified.chunking.table_serializer_version,
        "noise_rule_version": verified.chunking.noise_rule_version,
        "normalization_version": verified.chunking.normalization_version,
    }
    if current.manifest_values() != source_values:
        raise SystemExit("source package chunking configuration is incompatible with this runtime")
    return current


def _materialize_reusable_payloads(
    archive_path: Path,
    files: tuple[PackageFile, ...],
    staging: Path,
) -> dict[str, object]:
    """Copy only already-verified extraction payloads and omit old parent/child JSONL."""
    excluded = {"content_units.jsonl", "chunks.jsonl"}
    with ZipFile(archive_path) as archive:
        manifest = _mapping(json.loads(archive.read("manifest.json")), "manifest.json")
        for entry in files:
            if entry.path in excluded:
                continue
            target = staging / entry.path
            target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry.path))
    return manifest


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SystemExit(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


if __name__ == "__main__":
    raise SystemExit(main())
