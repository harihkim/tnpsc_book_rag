"""Materialize and type-check an immutable offline extraction package.

The package builder intentionally runs outside the application environment.  This module is the
application-side boundary: it verifies the archive first, copies only manifest-listed payloads to
a short-lived directory, and converts the JSONL records into the same domain values used by the
normal worker.  Persistence and embedding are deliberately separate stages.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from zipfile import ZipFile

from tnpsc_book_rag.pdf_extraction.chunking import (
    ExtractedContentUnit,
    ExtractedRetrievalChunk,
    TextbookChunkingResult,
)
from tnpsc_book_rag.pdf_extraction.docling import (
    ExtractedAsset,
    ExtractedBlock,
    ExtractedPage,
    ExtractionBundle,
)
from tnpsc_book_rag.pdf_extraction.package import (
    ExtractionPackageError,
    VerifiedExtractionPackage,
    verify_extraction_package,
)
from tnpsc_extraction.models import ChunkContentType, ContentUnitType, DisplayFormat


@dataclass(frozen=True, slots=True)
class MaterializedExtractionPackage:
    """Typed extraction records whose paths are valid only inside the context manager."""

    package: VerifiedExtractionPackage
    bundle: ExtractionBundle
    chunking: TextbookChunkingResult


@contextmanager
def materialize_extraction_package(
    archive_path: Path,
) -> Generator[MaterializedExtractionPackage]:
    """Verify and materialize a ZIP package into a temporary, application-owned directory."""
    verified_source = verify_extraction_package(archive_path)
    with TemporaryDirectory(prefix="tnpsc-package-") as temporary:
        temporary_root = Path(temporary)
        staged_archive = temporary_root / "verified-package.zip"
        shutil.copyfile(verified_source.archive_path, staged_archive)
        package = verify_extraction_package(staged_archive)
        root = temporary_root / "payload"
        root.mkdir(mode=0o750)
        with ZipFile(package.archive_path) as archive:
            for entry in package.files:
                target = root / entry.path
                target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
                target.write_bytes(archive.read(entry.path))
        bundle = _load_bundle(root, package)
        chunking = TextbookChunkingResult(
            content_units=_load_content_units(root / "content_units.jsonl"),
            chunks=_load_chunks(root / "chunks.jsonl"),
            implementation_version=package.chunking.implementation_version,
            tokenizer_identifier=package.chunking.tokenizer_identifier,
            tokenizer_revision=package.chunking.tokenizer_revision,
            config_fingerprint=package.chunking.config_fingerprint,
        )
        yield MaterializedExtractionPackage(
            package=package,
            bundle=bundle,
            chunking=chunking,
        )


def _load_bundle(root: Path, package: VerifiedExtractionPackage) -> ExtractionBundle:
    pages = _load_pages(root / "pages.jsonl")
    assets = _load_assets(root / "assets.jsonl", root)
    return ExtractionBundle(
        pages=tuple(pages),
        assets=tuple(assets),
        docling_json_path=root / "docling.json",
        page_count=package.page_count,
        docling_version=package.docling_version,
        config_fingerprint=package.config_fingerprint,
    )


def _load_pages(path: Path) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    for index, record in enumerate(_jsonl(path)):
        page_index = _integer(record.get("pdf_page_index"), f"pages[{index}].pdf_page_index")
        blocks_value = record.get("blocks")
        if not isinstance(blocks_value, list):
            raise ExtractionPackageError(f"pages[{index}].blocks must be a list")
        warnings_value = record.get("warnings")
        if not isinstance(warnings_value, list):
            raise ExtractionPackageError(f"pages[{index}].warnings must be a list")
        warnings = tuple(
            _mapping(value, f"pages[{index}].warnings[{warning_index}]")
            for warning_index, value in enumerate(warnings_value)
        )
        pages.append(
            ExtractedPage(
                pdf_page_index=page_index,
                width=_optional_number(record.get("width"), f"pages[{index}].width"),
                height=_optional_number(record.get("height"), f"pages[{index}].height"),
                raw_text=_string(record.get("raw_text"), f"pages[{index}].raw_text"),
                normalized_text=_string(
                    record.get("normalized_text"), f"pages[{index}].normalized_text"
                ),
                blocks=tuple(
                    _block(value, f"pages[{index}].blocks[{block_index}]")
                    for block_index, value in enumerate(blocks_value)
                ),
                warnings=warnings,
            )
        )
    return pages


def _block(value: object, field: str) -> ExtractedBlock:
    record = _mapping(value, field)
    char_span = record.get("char_span")
    return ExtractedBlock(
        text=_text(record.get("text"), f"{field}.text"),
        content_type=_text(record.get("content_type"), f"{field}.content_type"),
        page_index=_integer(record.get("page_index"), f"{field}.page_index"),
        bbox=_optional_mapping(record.get("bbox"), f"{field}.bbox"),
        char_span=_span(char_span, f"{field}.char_span"),
        heading_level=_optional_integer(record.get("heading_level"), f"{field}.heading_level"),
    )


def _load_assets(path: Path, root: Path) -> list[ExtractedAsset]:
    assets: list[ExtractedAsset] = []
    for index, record in enumerate(_jsonl(path)):
        relative = _text(record.get("path"), f"assets[{index}].path")
        image_path = root / relative
        if not relative.startswith("images/") or not image_path.is_file():
            raise ExtractionPackageError(f"assets[{index}] references no materialized image")
        assets.append(
            ExtractedAsset(
                ordinal=_integer(record.get("ordinal"), f"assets[{index}].ordinal"),
                page_index=_integer(record.get("page_index"), f"assets[{index}].page_index"),
                path=image_path,
                media_type=_text(record.get("media_type"), f"assets[{index}].media_type"),
                width=_positive_integer(record.get("width"), f"assets[{index}].width"),
                height=_positive_integer(record.get("height"), f"assets[{index}].height"),
                caption=_optional_text(record.get("caption"), f"assets[{index}].caption"),
                bounding_box=_optional_mapping(
                    record.get("bounding_box"), f"assets[{index}].bounding_box"
                ),
                coordinate_origin=_optional_text(
                    record.get("coordinate_origin"), f"assets[{index}].coordinate_origin"
                ),
                source_reference=_text(
                    record.get("source_reference"), f"assets[{index}].source_reference"
                ),
                provenance=_mapping(record.get("provenance"), f"assets[{index}].provenance"),
            )
        )
    return assets


def _load_content_units(path: Path) -> tuple[ExtractedContentUnit, ...]:
    content_units: list[ExtractedContentUnit] = []
    for index, record in enumerate(_jsonl(path)):
        field = f"content_units[{index}]"
        try:
            unit_type = ContentUnitType(_text(record.get("unit_type"), f"{field}.unit_type"))
            display_format = DisplayFormat(
                _text(record.get("display_format"), f"{field}.display_format")
            )
        except ValueError as error:
            raise ExtractionPackageError(f"{field} contains an unsupported enum value") from error
        content_units.append(
            ExtractedContentUnit(
                local_id=_text(record.get("local_id"), f"{field}.local_id"),
                sequence_number=_integer(record.get("sequence_number"), f"{field}.sequence_number"),
                unit_type=unit_type,
                display_text=_text(record.get("display_text"), f"{field}.display_text"),
                display_format=display_format,
                structured_content=_optional_mapping(
                    record.get("structured_content"), f"{field}.structured_content"
                ),
                section_path=_text_tuple(record.get("section_path"), f"{field}.section_path"),
                retrieval_eligible=_boolean(
                    record.get("retrieval_eligible"), f"{field}.retrieval_eligible"
                ),
                exclusion_reason=_optional_text(
                    record.get("exclusion_reason"), f"{field}.exclusion_reason"
                ),
                content_sha256=_sha256(record.get("content_sha256"), f"{field}.content_sha256"),
                page_indexes=_integer_tuple(record.get("page_indexes"), f"{field}.page_indexes"),
                docling_refs=_text_tuple(record.get("docling_refs"), f"{field}.docling_refs"),
                provenance=_mapping(record.get("provenance"), f"{field}.provenance"),
            )
        )
    return tuple(content_units)


def _load_chunks(path: Path) -> tuple[ExtractedRetrievalChunk, ...]:
    chunks: list[ExtractedRetrievalChunk] = []
    for index, record in enumerate(_jsonl(path)):
        field = f"chunks[{index}]"
        try:
            content_type = ChunkContentType(
                _text(record.get("content_type"), f"{field}.content_type")
            )
            display_format = DisplayFormat(
                _text(record.get("display_format"), f"{field}.display_format")
            )
        except ValueError as error:
            raise ExtractionPackageError(f"{field} contains an unsupported enum value") from error
        chunks.append(
            ExtractedRetrievalChunk(
                local_id=_text(record.get("local_id"), f"{field}.local_id"),
                parent_local_id=_text(record.get("parent_local_id"), f"{field}.parent_local_id"),
                sequence_number=_integer(record.get("sequence_number"), f"{field}.sequence_number"),
                display_text=_text(record.get("display_text"), f"{field}.display_text"),
                display_format=display_format,
                embedding_text=_text(record.get("embedding_text"), f"{field}.embedding_text"),
                chapter_title=_optional_text(record.get("chapter_title"), f"{field}.chapter_title"),
                section_path=_text_tuple(record.get("section_path"), f"{field}.section_path"),
                content_type=content_type,
                token_count=_positive_integer(record.get("token_count"), f"{field}.token_count"),
                display_sha256=_content_checksum(
                    record.get("display_sha256"),
                    record.get("display_text"),
                    f"{field}.display_sha256",
                ),
                embedding_sha256=_content_checksum(
                    record.get("embedding_sha256"),
                    record.get("embedding_text"),
                    f"{field}.embedding_sha256",
                ),
                page_indexes=_integer_tuple(record.get("page_indexes"), f"{field}.page_indexes"),
                docling_refs=_text_tuple(record.get("docling_refs"), f"{field}.docling_refs"),
                provenance=_mapping(record.get("provenance"), f"{field}.provenance"),
            )
        )
    return tuple(chunks)


def _jsonl(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_bytes().splitlines()
    except OSError as error:
        raise ExtractionPackageError(f"package payload could not be read: {path.name}") from error
    records: list[dict[str, object]] = []
    for index, line in enumerate(lines):
        try:
            records.append(_mapping(json.loads(line), f"{path.name}[{index}]"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ExtractionPackageError(f"{path.name}[{index}] is not valid JSON") from error
    return records


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ExtractionPackageError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExtractionPackageError(f"{field} must be non-blank text")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ExtractionPackageError(f"{field} must be text")
    return value


def _content_checksum(value: object, display_text: object, field: str) -> str:
    checksum = _sha256(value, field)
    if hashlib.sha256(_string(display_text, "display_text").encode()).hexdigest() != checksum:
        raise ExtractionPackageError(f"{field} does not match its text")
    return checksum


def _sha256(value: object, field: str) -> str:
    checksum = _text(value, field)
    if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
        raise ExtractionPackageError(f"{field} must be a lowercase SHA-256 digest")
    return checksum


def _text_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ExtractionPackageError(f"{field} must be a text list")
    return tuple(cast(list[str], value))


def _integer_tuple(value: object, field: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ExtractionPackageError(f"{field} must be an integer list")
    result = tuple(_integer(item, f"{field}[{index}]") for index, item in enumerate(value))
    if any(item < 0 for item in result):
        raise ExtractionPackageError(f"{field} must contain non-negative integers")
    return result


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ExtractionPackageError(f"{field} must be a boolean")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ExtractionPackageError(f"{field} must be an integer")
    return value


def _positive_integer(value: object, field: str) -> int:
    parsed = _integer(value, field)
    if parsed <= 0:
        raise ExtractionPackageError(f"{field} must be positive")
    return parsed


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _optional_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ExtractionPackageError(f"{field} must be a number or null")
    return float(value)


def _optional_mapping(value: object, field: str) -> dict[str, object] | None:
    if value is None:
        return None
    return _mapping(value, field)


def _span(value: object, field: str) -> tuple[int, int] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise ExtractionPackageError(f"{field} must contain two integers or null")
    first = _integer(value[0], f"{field}[0]")
    second = _integer(value[1], f"{field}[1]")
    if first < 0 or second < first:
        raise ExtractionPackageError(f"{field} must be an ordered character span")
    return first, second


__all__ = ["MaterializedExtractionPackage", "materialize_extraction_package"]
