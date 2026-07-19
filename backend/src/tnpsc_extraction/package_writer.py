"""Dependency-light serialization and publication helpers for package v2."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from tnpsc_extraction.models import (
    ExtractedAsset,
    ExtractedContentUnit,
    ExtractedPage,
    ExtractedRetrievalChunk,
)
from tnpsc_extraction.textbook_chunking import TextbookChunkingConfig


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for one package payload."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def json_dump(path: Path, value: object) -> None:
    """Write canonical human-inspectable manifest JSON."""
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def jsonl_dump(path: Path, values: Iterable[dict[str, object]]) -> None:
    """Write deterministic UTF-8 JSON Lines records."""
    with path.open("w", encoding="utf-8", newline="\n") as target:
        for value in values:
            target.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def page_payload(page: ExtractedPage) -> dict[str, object]:
    """Serialize one page without changing raw or normalized content."""
    return {
        "pdf_page_index": page.pdf_page_index,
        "width": page.width,
        "height": page.height,
        "raw_text": page.raw_text,
        "normalized_text": page.normalized_text,
        "blocks": [asdict(block) for block in page.blocks],
        "warnings": list(page.warnings),
    }


def asset_payload(asset: ExtractedAsset, output_root: Path) -> dict[str, object]:
    """Serialize one preserved image and bind metadata to its file hash."""
    return {
        "ordinal": asset.ordinal,
        "page_index": asset.page_index,
        "path": asset.path.relative_to(output_root).as_posix(),
        "media_type": asset.media_type,
        "sha256": sha256_file(asset.path),
        "width": asset.width,
        "height": asset.height,
        "caption": asset.caption,
        "bounding_box": asset.bounding_box,
        "coordinate_origin": asset.coordinate_origin,
        "source_reference": asset.source_reference,
        "provenance": asset.provenance,
    }


def content_unit_payload(content_unit: ExtractedContentUnit) -> dict[str, object]:
    """Serialize a semantic evidence parent using explicit JSON values."""
    return {
        "local_id": content_unit.local_id,
        "sequence_number": content_unit.sequence_number,
        "unit_type": content_unit.unit_type.value,
        "display_text": content_unit.display_text,
        "display_format": content_unit.display_format.value,
        "structured_content": content_unit.structured_content,
        "section_path": list(content_unit.section_path),
        "retrieval_eligible": content_unit.retrieval_eligible,
        "exclusion_reason": content_unit.exclusion_reason,
        "content_sha256": content_unit.content_sha256,
        "page_indexes": list(content_unit.page_indexes),
        "docling_refs": list(content_unit.docling_refs),
        "provenance": content_unit.provenance,
    }


def chunk_payload(chunk: ExtractedRetrievalChunk) -> dict[str, object]:
    """Serialize one retrieval child with exact display and embedding hashes."""
    return {
        "local_id": chunk.local_id,
        "parent_local_id": chunk.parent_local_id,
        "sequence_number": chunk.sequence_number,
        "display_text": chunk.display_text,
        "display_format": chunk.display_format.value,
        "embedding_text": chunk.embedding_text,
        "chapter_title": chunk.chapter_title,
        "section_path": list(chunk.section_path),
        "content_type": chunk.content_type.value,
        "token_count": chunk.token_count,
        "display_sha256": chunk.display_sha256,
        "embedding_sha256": chunk.embedding_sha256,
        "page_indexes": list(chunk.page_indexes),
        "docling_refs": list(chunk.docling_refs),
        "provenance": chunk.provenance,
    }


def chunking_manifest(config: TextbookChunkingConfig) -> dict[str, object]:
    """Build the exact fingerprinted package-v2 chunking contract."""
    return {
        "content_unit_schema_version": 1,
        "chunk_schema_version": 1,
        **config.manifest_values(),
        "config_fingerprint": config.fingerprint,
    }


def files_manifest(root: Path) -> list[dict[str, object]]:
    """Hash every package payload other than the self-referential manifest."""
    values: list[dict[str, object]] = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "manifest.json":
            continue
        values.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return values


def write_deterministic_zip(root: Path, archive_path: Path) -> None:
    """Write a reproducible archive without including the archive itself."""
    if archive_path.exists():
        raise FileExistsError(f"archive already exists: {archive_path}")
    archive_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = archive_path.with_suffix(f"{archive_path.suffix}.tmp")
    try:
        with ZipFile(temporary, "x", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
                relative = path.relative_to(root).as_posix()
                info = ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o640 << 16
                archive.writestr(info, path.read_bytes())
        os.replace(temporary, archive_path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "asset_payload",
    "chunk_payload",
    "chunking_manifest",
    "content_unit_payload",
    "files_manifest",
    "json_dump",
    "jsonl_dump",
    "page_payload",
    "sha256_file",
    "write_deterministic_zip",
]
