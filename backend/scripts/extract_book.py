#!/usr/bin/env python3
"""Extract one textbook into a checksummed, importable artifact package.

This script deliberately has no database or production-network dependency. It is intended for a
GPU notebook (for example, Google Colab) and produces a package that a future production importer
can verify before persisting it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def _configure_source_path() -> None:
    """Allow the script to run from a checkout without installing the backend application."""
    backend_root = Path(__file__).resolve().parents[1]
    source_root = backend_root / "src"
    import sys

    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json_dump(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _jsonl_dump(path: Path, values: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as target:
        for value in values:
            target.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def _page_payload(page: Any) -> dict[str, object]:
    return {
        "pdf_page_index": page.pdf_page_index,
        "width": page.width,
        "height": page.height,
        "raw_text": page.raw_text,
        "normalized_text": page.normalized_text,
        "blocks": [asdict(block) for block in page.blocks],
        "warnings": list(page.warnings),
    }


def _asset_payload(asset: Any, output_root: Path) -> dict[str, object]:
    return {
        "ordinal": asset.ordinal,
        "page_index": asset.page_index,
        "path": asset.path.relative_to(output_root).as_posix(),
        "media_type": asset.media_type,
        "sha256": _sha256(asset.path),
        "width": asset.width,
        "height": asset.height,
        "caption": asset.caption,
        "bounding_box": asset.bounding_box,
        "coordinate_origin": asset.coordinate_origin,
        "source_reference": asset.source_reference,
        "provenance": asset.provenance,
    }


def _chunk_payload(chunk: Any) -> dict[str, object]:
    payload = asdict(chunk)
    payload["content_type"] = chunk.content_type.value
    payload["section_path"] = list(chunk.section_path)
    return payload


def _files_manifest(root: Path) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "manifest.json":
            continue
        values.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return values


def _write_deterministic_zip(root: Path, archive_path: Path) -> None:
    """Write a reproducible archive without including the archive itself."""
    archive_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = archive_path.with_suffix(f"{archive_path.suffix}.tmp")
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
                relative = path.relative_to(root).as_posix()
                info = ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o640 << 16
                archive.writestr(info, path.read_bytes())
        os.replace(temporary, archive_path)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Digital PDF with an accessible text layer")
    parser.add_argument("output", type=Path, help="New directory for the extraction package")
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
        help="Docling accelerator; auto prefers CUDA and falls back to CPU",
    )
    parser.add_argument("--max-tokens", type=int, default=400)
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
    from tnpsc_extraction import DoclingExtractor, ExtractionError, chunk_pages

    arguments = _parse_args()
    source = arguments.pdf.expanduser().resolve()
    output = arguments.output.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"source PDF does not exist: {source}")
    if output.exists():
        raise SystemExit(f"output already exists; choose a new path: {output}")
    if arguments.max_tokens <= 0:
        raise SystemExit("--max-tokens must be positive")

    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
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
        extractor = DoclingExtractor(
            do_table_structure=not arguments.no_table_structure,
            accelerator_device=arguments.device,
            max_tokens=arguments.max_tokens,
        )
        try:
            bundle = extractor.extract(source, staging)
        except ExtractionError as error:
            raise SystemExit(f"extraction failed [{error.code}]: {error}") from error
        chunks = chunk_pages(bundle.pages, max_tokens=arguments.max_tokens)

        _jsonl_dump(staging / "pages.jsonl", [_page_payload(page) for page in bundle.pages])
        _jsonl_dump(
            staging / "assets.jsonl", [_asset_payload(asset, staging) for asset in bundle.assets]
        )
        _jsonl_dump(staging / "chunks.jsonl", [_chunk_payload(chunk) for chunk in chunks])
        if arguments.include_source:
            source_copy = staging / "source" / source.name
            source_copy.parent.mkdir(mode=0o750)
            shutil.copyfile(source, source_copy)

        manifest: dict[str, object] = {
            "manifest_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "source": {
                "filename": source.name,
                "sha256": _sha256(source),
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
                "max_tokens": arguments.max_tokens,
                "docling_version": bundle.docling_version,
                "config_fingerprint": bundle.config_fingerprint,
            },
            "counts": {
                "pages": bundle.page_count,
                "pages_with_text": sum(bool(page.normalized_text) for page in bundle.pages),
                "chunks": len(chunks),
                "assets": len(bundle.assets),
            },
            "files": _files_manifest(staging),
        }
        _json_dump(staging / "manifest.json", manifest)
        os.replace(staging, output)

    if arguments.archive is not None:
        archive = arguments.archive.expanduser().resolve()
        if archive == output or output in archive.parents:
            raise SystemExit("--archive must be outside the extraction output directory")
        _write_deterministic_zip(output, archive)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
