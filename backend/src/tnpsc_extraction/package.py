"""Pure verification boundary for offline extraction package v2 archives."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast
from zipfile import BadZipFile, ZipFile, ZipInfo

from tnpsc_extraction.models import ChunkContentType, ContentUnitType, DisplayFormat

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOCAL_ID = {
    "content_unit": re.compile(r"^U\d{6}$"),
    "chunk": re.compile(r"^C\d{6}$"),
}
_REQUIRED_PAYLOADS = frozenset(
    {
        "assets.jsonl",
        "chunks.jsonl",
        "content_units.jsonl",
        "docling.json",
        "pages.jsonl",
    }
)
_CHUNKING_CONFIG_FIELDS = frozenset(
    {
        "child_max_tokens",
        "display_serializer_version",
        "docling_version",
        "implementation_version",
        "merge_peers",
        "noise_rule_version",
        "normalization_version",
        "omit_header_on_overflow",
        "parent_hard_tokens",
        "parent_soft_tokens",
        "repeat_table_header",
        "table_serializer_version",
        "tokenizer_identifier",
        "tokenizer_revision",
    }
)
_CHUNKING_FIELDS = _CHUNKING_CONFIG_FIELDS | {
    "chunk_schema_version",
    "config_fingerprint",
    "content_unit_schema_version",
}
_MANIFEST_FIELDS = frozenset(
    {
        "book",
        "chunking",
        "counts",
        "created_at",
        "extraction",
        "files",
        "manifest_version",
        "runtime",
        "source",
    }
)
_BOOK_FIELDS = frozenset(
    {"edition", "language", "publisher", "standard", "subject", "term", "title"}
)
_SOURCE_FIELDS = frozenset({"filename", "sha256", "size_bytes"})
_RUNTIME_FIELDS = frozenset(
    {"cuda_available", "cuda_device", "cuda_runtime", "platform", "python", "torch"}
)
_EXTRACTION_FIELDS = frozenset(
    {
        "config_fingerprint",
        "device_requested",
        "device_resolved",
        "do_table_structure",
        "docling_version",
        "generate_picture_images",
    }
)
_COUNT_FIELDS = frozenset(
    {
        "assets",
        "chunks",
        "content_units",
        "pages",
        "pages_with_text",
        "retrieval_eligible_content_units",
    }
)
_PAGE_FIELDS = frozenset(
    {"blocks", "height", "normalized_text", "pdf_page_index", "raw_text", "warnings", "width"}
)
_BLOCK_FIELDS = frozenset(
    {"bbox", "char_span", "content_type", "heading_level", "page_index", "text"}
)
_CONTENT_UNIT_FIELDS = frozenset(
    {
        "content_sha256",
        "display_format",
        "display_text",
        "docling_refs",
        "exclusion_reason",
        "local_id",
        "page_indexes",
        "provenance",
        "retrieval_eligible",
        "section_path",
        "sequence_number",
        "structured_content",
        "unit_type",
    }
)
_CHUNK_FIELDS = frozenset(
    {
        "chapter_title",
        "content_type",
        "display_format",
        "display_sha256",
        "display_text",
        "docling_refs",
        "embedding_sha256",
        "embedding_text",
        "local_id",
        "page_indexes",
        "parent_local_id",
        "provenance",
        "section_path",
        "sequence_number",
        "token_count",
    }
)
_ASSET_FIELDS = frozenset(
    {
        "bounding_box",
        "caption",
        "coordinate_origin",
        "height",
        "media_type",
        "ordinal",
        "page_index",
        "path",
        "provenance",
        "sha256",
        "source_reference",
        "width",
    }
)
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
_MAX_IMAGE_BYTES = 100 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024


class ExtractionPackageError(ValueError):
    """Raised when an offline extraction package cannot be trusted for import."""


@dataclass(frozen=True, slots=True)
class PackageBookMetadata:
    """Curriculum identity required to register a textbook document."""

    title: str
    standard: int
    subject: str
    term: int
    language: str
    publisher: str
    edition: str


@dataclass(frozen=True, slots=True)
class PackageFile:
    """Integrity record for one immutable package payload."""

    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PackageChunkingMetadata:
    """Resolved parent-child chunking contract carried by package v2."""

    content_unit_schema_version: int
    chunk_schema_version: int
    implementation_version: str
    tokenizer_identifier: str
    tokenizer_revision: str
    child_max_tokens: int
    parent_soft_tokens: int
    parent_hard_tokens: int
    merge_peers: bool
    repeat_table_header: bool
    omit_header_on_overflow: bool
    display_serializer_version: str
    table_serializer_version: str
    noise_rule_version: str
    normalization_version: str
    config_fingerprint: str


@dataclass(frozen=True, slots=True)
class VerifiedExtractionPackage:
    """Validated v2 summary returned before any database or storage writes."""

    archive_path: Path
    book: PackageBookMetadata
    source_filename: str
    source_sha256: str
    source_size_bytes: int
    docling_version: str
    extraction_config_fingerprint: str
    chunking: PackageChunkingMetadata
    page_count: int
    content_unit_count: int
    chunk_count: int
    asset_count: int
    files: tuple[PackageFile, ...]

    @property
    def config_fingerprint(self) -> str:
        """Compatibility name for the Docling extraction fingerprint."""
        return self.extraction_config_fingerprint


def verify_extraction_package(archive_path: Path) -> VerifiedExtractionPackage:
    """Verify v2 integrity and all parent-child/provenance relationships without writes."""
    archive_path = archive_path.expanduser().resolve()
    if not archive_path.is_file() or archive_path.is_symlink():
        raise ExtractionPackageError("extraction package must be a regular file")

    try:
        with ZipFile(archive_path) as archive:
            return _verify_archive(archive_path, archive)
    except BadZipFile as error:
        raise ExtractionPackageError("extraction package is not a valid ZIP archive") from error
    except OSError as error:
        raise ExtractionPackageError("extraction package could not be read") from error


def _verify_archive(archive_path: Path, archive: ZipFile) -> VerifiedExtractionPackage:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise ExtractionPackageError("extraction package contains duplicate ZIP entries")
    info_by_name = {info.filename: info for info in infos}
    manifest_info = info_by_name.get("manifest.json")
    if manifest_info is None:
        raise ExtractionPackageError("extraction package is missing manifest.json")
    _verify_zip_info(manifest_info, maximum_bytes=_MAX_MANIFEST_BYTES)

    manifest = _mapping(_json_bytes(archive, "manifest.json"), "manifest.json")
    manifest_version = manifest.get("manifest_version")
    if manifest_version == 1:
        raise ExtractionPackageError(
            "extraction manifest version 1 is diagnostic-only; re-extract as package v2"
        )
    if manifest_version != 2:
        raise ExtractionPackageError("unsupported extraction manifest version")
    if set(manifest) != _MANIFEST_FIELDS:
        raise ExtractionPackageError("manifest must contain exactly the package-v2 fields")

    _timestamp(manifest.get("created_at"), "created_at")
    _runtime_metadata(manifest.get("runtime"))
    book = _book_metadata(manifest.get("book"))
    source = _mapping(manifest.get("source"), "source")
    if set(source) != _SOURCE_FIELDS:
        raise ExtractionPackageError("source must contain exactly the package-v2 fields")
    source_filename = _filename(source.get("filename"), "source.filename")
    source_sha256 = _digest(source.get("sha256"), "source.sha256")
    source_size_bytes = _positive_int(source.get("size_bytes"), "source.size_bytes")

    extraction = _mapping(manifest.get("extraction"), "extraction")
    if set(extraction) != _EXTRACTION_FIELDS:
        raise ExtractionPackageError("extraction must contain exactly the package-v2 fields")
    _extraction_runtime(extraction)
    docling_version = _text(
        extraction.get("docling_version"), "extraction.docling_version", maximum=100
    )
    extraction_config_fingerprint = _digest(
        extraction.get("config_fingerprint"),
        "extraction.config_fingerprint",
    )
    chunking = _chunking_metadata(manifest.get("chunking"), docling_version=docling_version)

    files = _file_manifest(manifest.get("files"))
    listed_paths = {entry.path for entry in files}
    missing_payloads = _REQUIRED_PAYLOADS - listed_paths
    if missing_payloads:
        missing = ", ".join(sorted(missing_payloads))
        raise ExtractionPackageError(f"manifest is missing required payloads: {missing}")
    unexpected_entries = set(names) - listed_paths - {"manifest.json"}
    if unexpected_entries:
        unexpected = ", ".join(sorted(unexpected_entries))
        raise ExtractionPackageError(f"ZIP contains unlisted payloads: {unexpected}")
    missing_entries = listed_paths - set(names)
    if missing_entries:
        missing = ", ".join(sorted(missing_entries))
        raise ExtractionPackageError(f"manifest references missing payloads: {missing}")

    _verify_payloads(archive, info_by_name, files)
    pages = _jsonl_records(archive, "pages.jsonl")
    content_units = _jsonl_records(archive, "content_units.jsonl")
    chunks = _jsonl_records(archive, "chunks.jsonl")
    assets = _jsonl_records(archive, "assets.jsonl")
    docling = _mapping(_json_bytes(archive, "docling.json"), "docling.json")
    docling_refs = _collect_docling_refs(docling)
    if not docling_refs:
        raise ExtractionPackageError("docling.json contains no source item references")

    _verify_records(
        manifest.get("counts"),
        pages=pages,
        content_units=content_units,
        chunks=chunks,
        assets=assets,
        listed_files={entry.path: entry for entry in files},
        docling_refs=docling_refs,
        chunking=chunking,
    )
    _verify_optional_source(
        files,
        source_filename=source_filename,
        source_sha256=source_sha256,
        source_size_bytes=source_size_bytes,
    )

    return VerifiedExtractionPackage(
        archive_path=archive_path,
        book=book,
        source_filename=source_filename,
        source_sha256=source_sha256,
        source_size_bytes=source_size_bytes,
        docling_version=docling_version,
        extraction_config_fingerprint=extraction_config_fingerprint,
        chunking=chunking,
        page_count=len(pages),
        content_unit_count=len(content_units),
        chunk_count=len(chunks),
        asset_count=len(assets),
        files=files,
    )


def _chunking_metadata(value: object, *, docling_version: str) -> PackageChunkingMetadata:
    chunking = _mapping(value, "chunking")
    if set(chunking) != _CHUNKING_FIELDS:
        raise ExtractionPackageError("chunking must contain exactly the package-v2 fields")
    content_unit_schema_version = _positive_int(
        chunking.get("content_unit_schema_version"), "chunking.content_unit_schema_version"
    )
    chunk_schema_version = _positive_int(
        chunking.get("chunk_schema_version"), "chunking.chunk_schema_version"
    )
    if content_unit_schema_version != 1 or chunk_schema_version != 1:
        raise ExtractionPackageError("unsupported parent-child payload schema version")
    configured_docling = _text(
        chunking.get("docling_version"), "chunking.docling_version", maximum=100
    )
    if configured_docling != docling_version:
        raise ExtractionPackageError("chunking Docling version does not match extraction")

    child_max_tokens = _bounded_int(
        chunking.get("child_max_tokens"),
        "chunking.child_max_tokens",
        minimum=1,
        maximum=512,
    )
    parent_soft_tokens = _positive_int(
        chunking.get("parent_soft_tokens"), "chunking.parent_soft_tokens"
    )
    parent_hard_tokens = _positive_int(
        chunking.get("parent_hard_tokens"), "chunking.parent_hard_tokens"
    )
    if parent_soft_tokens < child_max_tokens:
        raise ExtractionPackageError("parent soft target must be at least the child maximum")
    if parent_hard_tokens < parent_soft_tokens:
        raise ExtractionPackageError("parent hard target must be at least the soft target")
    merge_peers = _boolean(chunking.get("merge_peers"), "chunking.merge_peers")
    repeat_table_header = _boolean(
        chunking.get("repeat_table_header"), "chunking.repeat_table_header"
    )
    omit_header_on_overflow = _boolean(
        chunking.get("omit_header_on_overflow"), "chunking.omit_header_on_overflow"
    )
    if merge_peers or not repeat_table_header or omit_header_on_overflow:
        raise ExtractionPackageError("chunking merge and table-header policy is unsupported")

    config_values = {field: chunking[field] for field in _CHUNKING_CONFIG_FIELDS}
    recorded_fingerprint = _digest(
        chunking.get("config_fingerprint"), "chunking.config_fingerprint"
    )
    if _json_sha256(config_values) != recorded_fingerprint:
        raise ExtractionPackageError("chunking configuration fingerprint does not match")

    return PackageChunkingMetadata(
        content_unit_schema_version=content_unit_schema_version,
        chunk_schema_version=chunk_schema_version,
        implementation_version=_text(
            chunking.get("implementation_version"),
            "chunking.implementation_version",
            maximum=100,
        ),
        tokenizer_identifier=_text(
            chunking.get("tokenizer_identifier"),
            "chunking.tokenizer_identifier",
            maximum=300,
        ),
        tokenizer_revision=_text(
            chunking.get("tokenizer_revision"),
            "chunking.tokenizer_revision",
            maximum=200,
        ),
        child_max_tokens=child_max_tokens,
        parent_soft_tokens=parent_soft_tokens,
        parent_hard_tokens=parent_hard_tokens,
        merge_peers=merge_peers,
        repeat_table_header=repeat_table_header,
        omit_header_on_overflow=omit_header_on_overflow,
        display_serializer_version=_text(
            chunking.get("display_serializer_version"),
            "chunking.display_serializer_version",
            maximum=100,
        ),
        table_serializer_version=_text(
            chunking.get("table_serializer_version"),
            "chunking.table_serializer_version",
            maximum=100,
        ),
        noise_rule_version=_text(
            chunking.get("noise_rule_version"),
            "chunking.noise_rule_version",
            maximum=100,
        ),
        normalization_version=_text(
            chunking.get("normalization_version"),
            "chunking.normalization_version",
            maximum=100,
        ),
        config_fingerprint=recorded_fingerprint,
    )


def _verify_payloads(
    archive: ZipFile,
    info_by_name: dict[str, ZipInfo],
    files: tuple[PackageFile, ...],
) -> None:
    total_size = 0
    for entry in files:
        info = info_by_name[entry.path]
        maximum = _MAX_IMAGE_BYTES if entry.path.startswith("images/") else _MAX_PAYLOAD_BYTES
        _verify_zip_info(info, maximum_bytes=maximum)
        total_size += info.file_size
        if info.file_size != entry.size_bytes:
            raise ExtractionPackageError(f"payload size mismatch: {entry.path}")
        payload = archive.read(entry.path)
        if hashlib.sha256(payload).hexdigest() != entry.sha256:
            raise ExtractionPackageError(f"payload checksum mismatch: {entry.path}")
    if total_size > _MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise ExtractionPackageError("extraction package exceeds the uncompressed size limit")


def _verify_zip_info(info: ZipInfo, *, maximum_bytes: int) -> None:
    _safe_path(info.filename, f"ZIP entry {info.filename!r}")
    mode = info.external_attr >> 16
    if info.is_dir() or stat.S_IFMT(mode) == stat.S_IFLNK:
        raise ExtractionPackageError(f"ZIP entry is not a regular payload: {info.filename}")
    if info.flag_bits & 0x1:
        raise ExtractionPackageError(f"encrypted ZIP entries are unsupported: {info.filename}")
    if info.file_size < 0 or info.file_size > maximum_bytes:
        raise ExtractionPackageError(f"ZIP entry exceeds its size limit: {info.filename}")


def _verify_records(
    value: object,
    *,
    pages: list[dict[str, object]],
    content_units: list[dict[str, object]],
    chunks: list[dict[str, object]],
    assets: list[dict[str, object]],
    listed_files: dict[str, PackageFile],
    docling_refs: set[str],
    chunking: PackageChunkingMetadata,
) -> None:
    counts = _mapping(value, "counts")
    if set(counts) != _COUNT_FIELDS:
        raise ExtractionPackageError("counts must contain exactly the package-v2 fields")
    expected_pages = _positive_int(counts.get("pages"), "counts.pages")
    expected_content_units = _positive_int(
        counts.get("content_units"), "counts.content_units"
    )
    expected_chunks = _positive_int(counts.get("chunks"), "counts.chunks")
    expected_assets = _nonnegative_int(counts.get("assets"), "counts.assets")
    expected_pages_with_text = _nonnegative_int(
        counts.get("pages_with_text"), "counts.pages_with_text"
    )
    expected_eligible = _nonnegative_int(
        counts.get("retrieval_eligible_content_units"),
        "counts.retrieval_eligible_content_units",
    )
    if (
        len(pages) != expected_pages
        or len(content_units) != expected_content_units
        or len(chunks) != expected_chunks
        or len(assets) != expected_assets
    ):
        raise ExtractionPackageError("manifest counts do not match JSONL payloads")

    page_indexes = _verify_pages(pages)
    if expected_pages_with_text != sum(
        bool(_string(page.get("normalized_text"), "page.normalized_text").strip())
        for page in pages
    ):
        raise ExtractionPackageError("counts.pages_with_text does not match pages.jsonl")
    parents = _verify_content_units(content_units, page_indexes, docling_refs)
    eligible_count = sum(parent["retrieval_eligible"] is True for parent in parents.values())
    if expected_eligible != eligible_count:
        raise ExtractionPackageError(
            "counts.retrieval_eligible_content_units does not match content_units.jsonl"
        )
    _verify_chunks(chunks, parents, page_indexes, docling_refs, chunking)
    _verify_assets(assets, page_indexes, listed_files)


def _verify_pages(pages: list[dict[str, object]]) -> set[int]:
    indexes = [
        _nonnegative_int(page.get("pdf_page_index"), f"pages[{index}].pdf_page_index")
        for index, page in enumerate(pages)
    ]
    if indexes != list(range(len(pages))):
        raise ExtractionPackageError("pages.jsonl must contain contiguous zero-based page indexes")
    for index, page in enumerate(pages):
        if set(page) != _PAGE_FIELDS:
            raise ExtractionPackageError(f"pages[{index}] must contain exactly the v2 fields")
        _string(page.get("raw_text"), f"pages[{index}].raw_text")
        _string(page.get("normalized_text"), f"pages[{index}].normalized_text")
        _optional_positive_number(page.get("width"), f"pages[{index}].width")
        _optional_positive_number(page.get("height"), f"pages[{index}].height")
        blocks = page.get("blocks")
        if not isinstance(blocks, list):
            raise ExtractionPackageError(f"pages[{index}].blocks must be a list")
        for block_index, block_value in enumerate(blocks):
            block_field = f"pages[{index}].blocks[{block_index}]"
            block = _mapping(block_value, block_field)
            if set(block) != _BLOCK_FIELDS:
                raise ExtractionPackageError(f"{block_field} must contain exactly the v2 fields")
            _content_text(block.get("text"), f"{block_field}.text")
            _text(block.get("content_type"), f"{block_field}.content_type", maximum=100)
            if _nonnegative_int(block.get("page_index"), f"{block_field}.page_index") != index:
                raise ExtractionPackageError(f"{block_field} references the wrong page")
            _optional_mapping(block.get("bbox"), f"{block_field}.bbox")
            _optional_span(block.get("char_span"), f"{block_field}.char_span")
            _optional_positive_int(
                block.get("heading_level"), f"{block_field}.heading_level"
            )
        warnings = page.get("warnings")
        if not isinstance(warnings, list):
            raise ExtractionPackageError(f"pages[{index}].warnings must be a list")
        for warning_index, warning in enumerate(warnings):
            _mapping(warning, f"pages[{index}].warnings[{warning_index}]")
    return set(indexes)


def _verify_content_units(
    records: list[dict[str, object]],
    page_indexes: set[int],
    docling_refs: set[str],
) -> dict[str, dict[str, object]]:
    parents: dict[str, dict[str, object]] = {}
    for index, record in enumerate(records):
        field = f"content_units[{index}]"
        if set(record) != _CONTENT_UNIT_FIELDS:
            raise ExtractionPackageError(f"{field} must contain exactly the v2 fields")
        local_id = _ordered_local_id(record, index, field=field, kind="content_unit")
        unit_type = _enum_value(
            record.get("unit_type"), f"{field}.unit_type", ContentUnitType
        )
        display_text = _content_text(record.get("display_text"), f"{field}.display_text")
        display_format = _enum_value(
            record.get("display_format"), f"{field}.display_format", DisplayFormat
        )
        structured_content = record.get("structured_content")
        if structured_content is not None and not isinstance(structured_content, dict):
            raise ExtractionPackageError(f"{field}.structured_content must be an object or null")
        if unit_type == ContentUnitType.TABLE.value and (
            display_format != DisplayFormat.MARKDOWN.value
            or not isinstance(structured_content, dict)
        ):
            raise ExtractionPackageError(
                f"{field} table parents require Markdown and structured content"
            )
        section_path = _text_list(record.get("section_path"), f"{field}.section_path")
        retrieval_eligible = _boolean(
            record.get("retrieval_eligible"), f"{field}.retrieval_eligible"
        )
        exclusion_reason = _optional_text(
            record.get("exclusion_reason"), f"{field}.exclusion_reason", maximum=200
        )
        if retrieval_eligible == (exclusion_reason is not None):
            raise ExtractionPackageError(
                f"{field}.exclusion_reason must be null exactly when retrieval is eligible"
            )
        checksum = _digest(record.get("content_sha256"), f"{field}.content_sha256")
        expected_checksum = _json_sha256(
            {
                "display_format": display_format,
                "display_text": display_text,
                "structured_content": structured_content,
            }
        )
        if checksum != expected_checksum:
            raise ExtractionPackageError(f"{field}.content_sha256 does not match parent content")
        parent_pages = _page_reference_list(
            record.get("page_indexes"), f"{field}.page_indexes", page_indexes
        )
        parent_refs = _docling_reference_list(
            record.get("docling_refs"), f"{field}.docling_refs", docling_refs
        )
        _mapping(record.get("provenance"), f"{field}.provenance")
        if local_id in parents:
            raise ExtractionPackageError(f"duplicate content unit ID: {local_id}")
        parents[local_id] = {
            "unit_type": unit_type,
            "display_text": display_text,
            "structured_content": structured_content,
            "section_path": section_path,
            "retrieval_eligible": retrieval_eligible,
            "child_displays": [],
            "child_count": 0,
            "page_indexes": parent_pages,
            "docling_refs": parent_refs,
        }
    return parents


def _verify_chunks(
    records: list[dict[str, object]],
    parents: dict[str, dict[str, object]],
    page_indexes: set[int],
    docling_refs: set[str],
    chunking: PackageChunkingMetadata,
) -> None:
    for index, record in enumerate(records):
        field = f"chunks[{index}]"
        if set(record) != _CHUNK_FIELDS:
            raise ExtractionPackageError(f"{field} must contain exactly the v2 fields")
        _ordered_local_id(record, index, field=field, kind="chunk")
        parent_id = _text(record.get("parent_local_id"), f"{field}.parent_local_id", maximum=7)
        parent = parents.get(parent_id)
        if parent is None:
            raise ExtractionPackageError(f"{field} references unknown parent: {parent_id}")
        display_text = _content_text(record.get("display_text"), f"{field}.display_text")
        _enum_value(record.get("display_format"), f"{field}.display_format", DisplayFormat)
        embedding_text = _content_text(
            record.get("embedding_text"), f"{field}.embedding_text"
        )
        _optional_text(record.get("chapter_title"), f"{field}.chapter_title", maximum=500)
        section_path = _text_list(record.get("section_path"), f"{field}.section_path")
        if section_path != parent["section_path"]:
            raise ExtractionPackageError(f"{field}.section_path does not match its parent")
        content_type = _enum_value(
            record.get("content_type"), f"{field}.content_type", ChunkContentType
        )
        parent_is_table = parent["unit_type"] == ContentUnitType.TABLE.value
        if (content_type == ChunkContentType.TABLE.value) != parent_is_table:
            raise ExtractionPackageError(f"{field} table type does not match its parent")
        token_count = _positive_int(record.get("token_count"), f"{field}.token_count")
        if token_count > chunking.child_max_tokens:
            raise ExtractionPackageError(f"{field}.token_count exceeds the configured maximum")
        if _digest(record.get("display_sha256"), f"{field}.display_sha256") != _text_sha256(
            display_text
        ):
            raise ExtractionPackageError(f"{field}.display_sha256 does not match display_text")
        if _digest(
            record.get("embedding_sha256"), f"{field}.embedding_sha256"
        ) != _text_sha256(embedding_text):
            raise ExtractionPackageError(
                f"{field}.embedding_sha256 does not match embedding_text"
            )
        child_pages = _page_reference_list(
            record.get("page_indexes"), f"{field}.page_indexes", page_indexes
        )
        if not set(child_pages) <= set(cast(tuple[int, ...], parent["page_indexes"])):
            raise ExtractionPackageError(f"{field}.page_indexes are outside its parent")
        child_refs = _docling_reference_list(
            record.get("docling_refs"), f"{field}.docling_refs", docling_refs
        )
        if not set(child_refs) <= set(cast(tuple[str, ...], parent["docling_refs"])):
            raise ExtractionPackageError(f"{field}.docling_refs are outside its parent")
        _mapping(record.get("provenance"), f"{field}.provenance")
        cast(list[str], parent["child_displays"]).append(display_text)
        parent["child_count"] = cast(int, parent["child_count"]) + 1

    for parent_id, parent in parents.items():
        child_count = cast(int, parent["child_count"])
        if child_count == 0:
            raise ExtractionPackageError(f"content unit has no retrieval child: {parent_id}")
        if parent["unit_type"] == ContentUnitType.TABLE.value and child_count > 1:
            headers = _table_repeated_headers(
                cast(dict[str, object], parent["structured_content"])
            )
            for display_text in cast(list[str], parent["child_displays"]):
                missing = [
                    header
                    for header in headers
                    if header.casefold() not in display_text.casefold()
                ]
                if missing:
                    raise ExtractionPackageError(
                        f"split table child for {parent_id} does not repeat its headers"
                    )


def _table_repeated_headers(structured: dict[str, object]) -> tuple[str, ...]:
    cells = structured.get("table_cells")
    if not isinstance(cells, list):
        raise ExtractionPackageError("table structured content must contain table_cells")
    headers: dict[int, str] = {}
    for index, value in enumerate(cells):
        cell = _mapping(value, f"table_cells[{index}]")
        if cell.get("column_header") is True:
            column = _nonnegative_int(
                cell.get("start_col_offset_idx"),
                f"table_cells[{index}].start_col_offset_idx",
            )
            headers.setdefault(
                column,
                _content_text(cell.get("text"), f"table_cells[{index}].text"),
            )
    ordered = tuple(headers[column] for column in sorted(headers))
    return ordered[1:] if len(ordered) > 1 else ordered


def _verify_assets(
    assets: list[dict[str, object]],
    page_indexes: set[int],
    listed_files: dict[str, PackageFile],
) -> None:
    asset_paths: set[str] = set()
    file_paths = {path for path in listed_files if path.startswith("images/")}
    for index, asset in enumerate(assets):
        field = f"assets[{index}]"
        if set(asset) != _ASSET_FIELDS:
            raise ExtractionPackageError(f"{field} must contain exactly the v2 fields")
        _nonnegative_int(asset.get("ordinal"), f"{field}.ordinal")
        page_index = _nonnegative_int(asset.get("page_index"), f"{field}.page_index")
        if page_index not in page_indexes:
            raise ExtractionPackageError(f"asset references unknown page: {page_index}")
        path = _safe_path(asset.get("path"), f"{field}.path")
        if not path.startswith("images/") or path not in file_paths:
            raise ExtractionPackageError(f"asset references an unlisted image: {path}")
        if path in asset_paths:
            raise ExtractionPackageError(f"duplicate asset path: {path}")
        asset_paths.add(path)
        asset_sha256 = _digest(asset.get("sha256"), f"{field}.sha256")
        if asset_sha256 != listed_files[path].sha256:
            raise ExtractionPackageError(f"{field}.sha256 does not match its image payload")
        _text(asset.get("media_type"), f"{field}.media_type", maximum=100)
        _positive_int(asset.get("width"), f"{field}.width")
        _positive_int(asset.get("height"), f"{field}.height")
        _optional_text(asset.get("caption"), f"{field}.caption", maximum=10_000)
        _optional_mapping(asset.get("bounding_box"), f"{field}.bounding_box")
        _optional_text(
            asset.get("coordinate_origin"), f"{field}.coordinate_origin", maximum=100
        )
        _text(
            asset.get("source_reference"), f"{field}.source_reference", maximum=500
        )
        _mapping(asset.get("provenance"), f"{field}.provenance")
    if asset_paths != file_paths:
        raise ExtractionPackageError("package contains an image without asset metadata")


def _verify_optional_source(
    files: tuple[PackageFile, ...],
    *,
    source_filename: str,
    source_sha256: str,
    source_size_bytes: int,
) -> None:
    extras = [
        entry
        for entry in files
        if entry.path not in _REQUIRED_PAYLOADS and not entry.path.startswith("images/")
    ]
    if not extras:
        return
    expected_path = f"source/{source_filename}"
    if len(extras) != 1 or extras[0].path != expected_path:
        raise ExtractionPackageError("package contains an unsupported listed payload")
    if extras[0].sha256 != source_sha256 or extras[0].size_bytes != source_size_bytes:
        raise ExtractionPackageError("included source PDF does not match source metadata")


def _book_metadata(value: object) -> PackageBookMetadata:
    book = _mapping(value, "book")
    if set(book) != _BOOK_FIELDS:
        raise ExtractionPackageError("book must contain exactly the package-v2 fields")
    language = _text(book.get("language"), "book.language", maximum=32).casefold()
    if language != "english":
        raise ExtractionPackageError("only english extraction packages are supported")
    return PackageBookMetadata(
        title=_text(book.get("title"), "book.title", maximum=500),
        standard=_bounded_int(book.get("standard"), "book.standard", minimum=6, maximum=10),
        subject=_text(book.get("subject"), "book.subject", maximum=200),
        term=_bounded_int(book.get("term"), "book.term", minimum=1, maximum=3),
        language=language,
        publisher=_text(book.get("publisher"), "book.publisher", maximum=300),
        edition=_text(book.get("edition"), "book.edition", maximum=200),
    )


def _file_manifest(value: object) -> tuple[PackageFile, ...]:
    if not isinstance(value, list):
        raise ExtractionPackageError("manifest.files must be a list")
    entries: list[PackageFile] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        payload = _mapping(item, f"manifest.files[{index}]")
        if set(payload) != {"path", "sha256", "size_bytes"}:
            raise ExtractionPackageError(
                f"manifest.files[{index}] must contain exactly the v2 fields"
            )
        path = _safe_path(payload.get("path"), f"manifest.files[{index}].path")
        if path in seen:
            raise ExtractionPackageError(f"manifest contains duplicate payload: {path}")
        seen.add(path)
        entries.append(
            PackageFile(
                path=path,
                size_bytes=_nonnegative_int(
                    payload.get("size_bytes"), f"manifest.files[{index}].size_bytes"
                ),
                sha256=_digest(payload.get("sha256"), f"manifest.files[{index}].sha256"),
            )
        )
    if "manifest.json" in seen:
        raise ExtractionPackageError("manifest.json must not checksum itself")
    return tuple(entries)


def _ordered_local_id(
    record: dict[str, object],
    index: int,
    *,
    field: str,
    kind: str,
) -> str:
    local_id = _text(record.get("local_id"), f"{field}.local_id", maximum=7)
    sequence = _nonnegative_int(record.get("sequence_number"), f"{field}.sequence_number")
    prefix = "U" if kind == "content_unit" else "C"
    if (
        _LOCAL_ID[kind].fullmatch(local_id) is None
        or local_id != f"{prefix}{index:06d}"
        or sequence != index
    ):
        raise ExtractionPackageError(f"{field} ID and sequence must be contiguous and ordered")
    return local_id


def _page_reference_list(value: object, field: str, page_indexes: set[int]) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ExtractionPackageError(f"{field} must be a non-empty page index list")
    parsed = tuple(_nonnegative_int(item, f"{field}[]") for item in value)
    if parsed != tuple(sorted(set(parsed))) or not set(parsed) <= page_indexes:
        raise ExtractionPackageError(f"{field} must contain ordered known page indexes")
    return parsed


def _docling_reference_list(value: object, field: str, known_refs: set[str]) -> tuple[str, ...]:
    parsed = _text_list(value, field)
    if not parsed or len(parsed) != len(set(parsed)) or not set(parsed) <= known_refs:
        raise ExtractionPackageError(f"{field} must contain unique known Docling references")
    return parsed


def _text_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ExtractionPackageError(f"{field} must be a text list")
    return tuple(_text(item, f"{field}[]", maximum=500) for item in value)


def _collect_docling_refs(value: object) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        self_ref = value.get("self_ref")
        if isinstance(self_ref, str) and self_ref:
            refs.add(self_ref)
        for child in value.values():
            refs.update(_collect_docling_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_collect_docling_refs(child))
    return refs


def _runtime_metadata(value: object) -> None:
    runtime = _mapping(value, "runtime")
    if set(runtime) != _RUNTIME_FIELDS:
        raise ExtractionPackageError("runtime must contain exactly the package-v2 fields")
    _text(runtime.get("python"), "runtime.python", maximum=100)
    _text(runtime.get("platform"), "runtime.platform", maximum=500)
    _optional_text(runtime.get("torch"), "runtime.torch", maximum=100)
    _optional_text(runtime.get("cuda_runtime"), "runtime.cuda_runtime", maximum=100)
    cuda_available = _boolean(runtime.get("cuda_available"), "runtime.cuda_available")
    cuda_device = _optional_text(runtime.get("cuda_device"), "runtime.cuda_device", maximum=500)
    if cuda_available != (cuda_device is not None):
        raise ExtractionPackageError(
            "runtime.cuda_device must be present exactly when CUDA is available"
        )


def _extraction_runtime(extraction: dict[str, object]) -> None:
    requested = _text(
        extraction.get("device_requested"), "extraction.device_requested", maximum=20
    )
    resolved = _text(
        extraction.get("device_resolved"), "extraction.device_resolved", maximum=20
    )
    if requested not in {"auto", "cpu", "cuda"} or resolved not in {"cpu", "cuda"}:
        raise ExtractionPackageError("extraction device selection is unsupported")
    if requested in {"cpu", "cuda"} and resolved != requested:
        raise ExtractionPackageError("resolved extraction device contradicts the request")
    _boolean(extraction.get("do_table_structure"), "extraction.do_table_structure")
    if not _boolean(
        extraction.get("generate_picture_images"),
        "extraction.generate_picture_images",
    ):
        raise ExtractionPackageError("package v2 requires preserved picture images")


def _json_bytes(archive: ZipFile, path: str) -> object:
    try:
        return json.loads(archive.read(path))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExtractionPackageError(f"{path} is not valid JSON") from error


def _jsonl_records(archive: ZipFile, path: str) -> list[dict[str, object]]:
    try:
        lines = archive.read(path).splitlines()
    except KeyError as error:
        raise ExtractionPackageError(f"package is missing {path}") from error
    records: list[dict[str, object]] = []
    for index, line in enumerate(lines):
        try:
            records.append(_mapping(json.loads(line), f"{path}[{index}]"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ExtractionPackageError(f"{path}[{index}] is not valid JSON") from error
    return records


def _timestamp(value: object, field: str) -> datetime:
    text = _text(value, field, maximum=100)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ExtractionPackageError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExtractionPackageError(f"{field} must include a timezone offset")
    return parsed


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ExtractionPackageError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _content_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExtractionPackageError(f"{field} must be non-blank text")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ExtractionPackageError(f"{field} must be text")
    return value


def _text(value: object, field: str, *, maximum: int) -> str:
    normalized = _content_text(value, field).strip()
    if len(normalized) > maximum:
        raise ExtractionPackageError(f"{field} exceeds its maximum length")
    return normalized


def _optional_text(value: object, field: str, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, field, maximum=maximum)


def _optional_mapping(value: object, field: str) -> dict[str, object] | None:
    if value is None:
        return None
    return _mapping(value, field)


def _optional_positive_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field)


def _optional_positive_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ExtractionPackageError(f"{field} must be a positive number or null")
    return float(value)


def _optional_span(value: object, field: str) -> tuple[int, int] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise ExtractionPackageError(f"{field} must contain two integers or null")
    start = _nonnegative_int(value[0], f"{field}[0]")
    end = _nonnegative_int(value[1], f"{field}[1]")
    if end < start:
        raise ExtractionPackageError(f"{field} must be an ordered character span")
    return start, end


def _filename(value: object, field: str) -> str:
    filename = _text(value, field, maximum=500)
    if "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise ExtractionPackageError(f"{field} must be a plain filename")
    return filename


def _safe_path(value: object, field: str) -> str:
    path = _text(value, field, maximum=500)
    parsed = PurePosixPath(path)
    if path.startswith("/") or "\\" in path or ".." in parsed.parts or parsed.as_posix() != path:
        raise ExtractionPackageError(f"{field} must be a safe relative POSIX path")
    return path


def _digest(value: object, field: str) -> str:
    digest = _text(value, field, maximum=64)
    if _SHA256.fullmatch(digest) is None:
        raise ExtractionPackageError(f"{field} must be a lowercase SHA-256 digest")
    return digest


def _enum_value(value: object, field: str, enum_type: type[Any]) -> str:
    parsed = _text(value, field, maximum=100)
    try:
        enum_type(parsed)
    except ValueError as error:
        raise ExtractionPackageError(f"{field} is unsupported") from error
    return parsed


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ExtractionPackageError(f"{field} must be a boolean")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    return _bounded_int(value, field, minimum=0, maximum=None)


def _positive_int(value: object, field: str) -> int:
    return _bounded_int(value, field, minimum=1, maximum=None)


def _bounded_int(value: object, field: str, *, minimum: int, maximum: int | None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ExtractionPackageError(f"{field} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ExtractionPackageError(f"{field} must be an integer <= {maximum}")
    return value


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_sha256(value: dict[str, object]) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return _text_sha256(payload)


__all__ = [
    "ExtractionPackageError",
    "PackageBookMetadata",
    "PackageChunkingMetadata",
    "PackageFile",
    "VerifiedExtractionPackage",
    "verify_extraction_package",
]
