"""Native Docling parent-child chunking for English textbooks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from importlib.metadata import version
from typing import TYPE_CHECKING, Any, cast, override

from docling_core.transforms.chunker import DocChunk, HybridChunker
from docling_core.transforms.chunker.hierarchical_chunker import ChunkingDocSerializer
from docling_core.transforms.chunker.line_chunker import LineBasedTokenChunker
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.transforms.serializer.base import BaseDocSerializer
from docling_core.types.doc import DocItemLabel, DoclingDocument, TableItem

from tnpsc_extraction.models import (
    ChunkContentType,
    ContentUnitType,
    DisplayFormat,
    ExtractedContentUnit,
    ExtractedRetrievalChunk,
    TextbookChunkingResult,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

TEXTBOOK_CHUNKER_VERSION = "textbook-hybrid-v1"
DEFAULT_TOKENIZER_IDENTIFIER = "BAAI/bge-small-en-v1.5"
# This revision includes the model's safetensors files and predates unrelated ONNX additions.
DEFAULT_TOKENIZER_REVISION = "c202d20b1417db2e392c8aad36b6056867218dce"
_MODEL_MAX_TOKENS = 512
_PROTECTED_UNIT_TYPES = {
    ContentUnitType.DEFINITION,
    ContentUnitType.LAW,
    ContentUnitType.SOLVED_EXAMPLE,
    ContentUnitType.ACTIVITY,
}
_DEFINITION = re.compile(r"^(?:definition\b|meaning\b|define\b)", re.IGNORECASE)
_LAW = re.compile(r"^(?:law\b|.*\blaw of\b|theorem\b|principle\b)", re.IGNORECASE)
_EXAMPLE = re.compile(r"^(?:(?:worked|solved)\s+)?example\b", re.IGNORECASE)
_ACTIVITY = re.compile(r"^(?:activity\b|try this\b|do you know\b)", re.IGNORECASE)
_INDD_MARKER = re.compile(r"^\S+\.indd\s+\d+\s*$", re.IGNORECASE)
_NOISE_LABELS = {DocItemLabel.PAGE_HEADER.value, DocItemLabel.PAGE_FOOTER.value}


@dataclass(frozen=True, slots=True)
class TextbookChunkingConfig:
    """All values that can affect deterministic textbook chunk output."""

    docling_version: str = version("docling")
    implementation_version: str = TEXTBOOK_CHUNKER_VERSION
    tokenizer_identifier: str = DEFAULT_TOKENIZER_IDENTIFIER
    tokenizer_revision: str = DEFAULT_TOKENIZER_REVISION
    child_max_tokens: int = 256
    parent_soft_tokens: int = 800
    parent_hard_tokens: int = 1_200
    merge_peers: bool = False
    repeat_table_header: bool = True
    omit_header_on_overflow: bool = False
    display_serializer_version: str = "plain-markdown-v1"
    table_serializer_version: str = "docling-triplet-v1"
    noise_rule_version: str = "english-margin-noise-v1"
    normalization_version: str = "unicode-whitespace-v1"

    def __post_init__(self) -> None:
        """Reject configurations that cannot produce valid BGE Small chunks."""
        required_strings = {
            "docling_version": self.docling_version,
            "implementation_version": self.implementation_version,
            "tokenizer_identifier": self.tokenizer_identifier,
            "tokenizer_revision": self.tokenizer_revision,
            "display_serializer_version": self.display_serializer_version,
            "table_serializer_version": self.table_serializer_version,
            "noise_rule_version": self.noise_rule_version,
            "normalization_version": self.normalization_version,
        }
        for field_name, value in required_strings.items():
            if not value.strip():
                raise ValueError(f"{field_name} must not be blank")
        if not 0 < self.child_max_tokens <= _MODEL_MAX_TOKENS:
            raise ValueError(f"child_max_tokens must be between 1 and {_MODEL_MAX_TOKENS}")
        if self.parent_soft_tokens <= 0:
            raise ValueError("parent_soft_tokens must be positive")
        if self.parent_hard_tokens < self.parent_soft_tokens:
            raise ValueError("parent_hard_tokens must be at least parent_soft_tokens")
        if self.merge_peers:
            raise ValueError(
                "merge_peers must remain false until parent-aware merging is implemented"
            )
        if not self.repeat_table_header:
            raise ValueError(
                "repeat_table_header must remain true for independently useful table chunks"
            )
        if self.omit_header_on_overflow:
            raise ValueError(
                "omit_header_on_overflow must remain false for table chunk consistency"
            )

    def manifest_values(self) -> dict[str, object]:
        """Return canonical JSON-compatible values for package manifests."""
        return asdict(self)

    @property
    def fingerprint(self) -> str:
        """Identify the complete resolved configuration by its canonical JSON hash."""
        payload = json.dumps(
            self.manifest_values(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _Candidate:
    """One native HybridChunker result before semantic parent assignment."""

    chunk: DocChunk
    display_text: str
    embedding_text: str
    section_path: tuple[str, ...]
    unit_type: ContentUnitType
    content_type: ChunkContentType
    page_indexes: tuple[int, ...]
    docling_refs: tuple[str, ...]
    provenance: dict[str, object]
    retrieval_eligible: bool
    exclusion_reason: str | None


@dataclass(slots=True)
class _ParentGroup:
    """Mutable construction value that never leaves the chunker."""

    candidates: list[_Candidate]
    unit_type: ContentUnitType
    section_path: tuple[str, ...]
    retrieval_eligible: bool
    exclusion_reason: str | None


class _AvailableLengthTokenizer(BaseTokenizer):
    """Delegate tokenization while exposing a smaller limit to Docling's line splitter."""

    delegate: BaseTokenizer
    max_tokens: int

    @override
    def count_tokens(self, text: str) -> int:
        return self.delegate.count_tokens(text)

    @override
    def get_max_tokens(self) -> int:
        return self.max_tokens

    @override
    def get_tokenizer(self) -> Any:
        return self.delegate.get_tokenizer()


class _BoundedHybridChunker(HybridChunker):
    """Keep table chunks inside the space left after headings and captions."""

    @override
    def segment(
        self,
        doc_chunk: DocChunk,
        available_length: int,
        doc_serializer: BaseDocSerializer,
    ) -> list[str]:
        if (
            self.repeat_table_header
            and isinstance(doc_serializer, ChunkingDocSerializer)
            and len(doc_chunk.meta.doc_items) == 1
            and isinstance(doc_chunk.meta.doc_items[0], TableItem)
        ):
            header_lines, body_lines = doc_serializer.table_serializer.get_header_and_body_lines(
                table_text=doc_chunk.text
            )
            bounded_tokenizer = _AvailableLengthTokenizer(
                delegate=self.tokenizer,
                max_tokens=available_length,
            )
            return LineBasedTokenChunker(
                tokenizer=bounded_tokenizer,
                prefix="\n".join(header_lines),
                omit_prefix_on_overflow=self.omit_header_on_overflow,
                serializer_provider=self.serializer_provider,
            ).chunk_text(lines=body_lines)
        return super().segment(doc_chunk, available_length, doc_serializer)


class TextbookChunker:
    """Build semantic parents and exact-token child chunks from a Docling document."""

    def __init__(
        self,
        config: TextbookChunkingConfig | None = None,
        *,
        tokenizer: BaseTokenizer | None = None,
    ) -> None:
        self.config = config or TextbookChunkingConfig()
        self.tokenizer = tokenizer or HuggingFaceTokenizer.from_pretrained(
            self.config.tokenizer_identifier,
            max_tokens=self.config.child_max_tokens,
            revision=self.config.tokenizer_revision,
        )
        if self.tokenizer.get_max_tokens() != self.config.child_max_tokens:
            raise ValueError("tokenizer maximum must equal child_max_tokens")
        self._hybrid = _BoundedHybridChunker(
            tokenizer=self.tokenizer,
            repeat_table_header=self.config.repeat_table_header,
            merge_peers=self.config.merge_peers,
            omit_header_on_overflow=self.config.omit_header_on_overflow,
        )

    def chunk(self, document: DoclingDocument) -> TextbookChunkingResult:
        """Return deterministic semantic parents and retrieval children."""
        candidates = tuple(
            self._candidate(cast("DocChunk", chunk)) for chunk in self._hybrid.chunk(document)
        )
        groups = self._group_candidates(candidates)
        content_units: list[ExtractedContentUnit] = []
        children: list[ExtractedRetrievalChunk] = []

        for parent_sequence, group in enumerate(groups):
            parent_local_id = f"U{parent_sequence:06d}"
            parent = self._make_parent(document, parent_local_id, parent_sequence, group)
            content_units.append(parent)
            for candidate in group.candidates:
                token_count = self.tokenizer.count_tokens(candidate.embedding_text)
                if token_count > self.config.child_max_tokens:
                    raise ValueError(
                        "HybridChunker emitted a contextualized child above child_max_tokens"
                    )
                child_sequence = len(children)
                children.append(
                    ExtractedRetrievalChunk(
                        local_id=f"C{child_sequence:06d}",
                        parent_local_id=parent_local_id,
                        sequence_number=child_sequence,
                        display_text=candidate.display_text,
                        display_format=DisplayFormat.PLAIN_TEXT,
                        embedding_text=candidate.embedding_text,
                        chapter_title=(
                            candidate.section_path[0] if candidate.section_path else None
                        ),
                        section_path=candidate.section_path,
                        content_type=candidate.content_type,
                        token_count=token_count,
                        display_sha256=_text_sha256(candidate.display_text),
                        embedding_sha256=_text_sha256(candidate.embedding_text),
                        page_indexes=candidate.page_indexes,
                        docling_refs=candidate.docling_refs,
                        provenance=candidate.provenance,
                    )
                )

        return TextbookChunkingResult(
            content_units=tuple(content_units),
            chunks=tuple(children),
            implementation_version=self.config.implementation_version,
            tokenizer_identifier=self.config.tokenizer_identifier,
            tokenizer_revision=self.config.tokenizer_revision,
            config_fingerprint=self.config.fingerprint,
        )

    def _candidate(self, chunk: DocChunk) -> _Candidate:
        display_text = chunk.text.strip()
        section_path = tuple(chunk.meta.headings or ())
        labels = tuple(item.label.value for item in chunk.meta.doc_items)
        docling_refs = tuple(dict.fromkeys(item.self_ref for item in chunk.meta.doc_items))
        page_indexes = tuple(
            sorted(
                {
                    provenance.page_no - 1
                    for item in chunk.meta.doc_items
                    for provenance in item.prov
                }
            )
        )
        unit_type = _classify_unit(section_path, display_text, labels)
        exclusion_reason = _exclusion_reason(labels, display_text)
        return _Candidate(
            chunk=chunk,
            display_text=display_text,
            embedding_text=self._hybrid.contextualize(chunk).strip(),
            section_path=section_path,
            unit_type=unit_type,
            content_type=_classify_content(labels),
            page_indexes=page_indexes,
            docling_refs=docling_refs,
            provenance=_provenance(chunk),
            retrieval_eligible=exclusion_reason is None,
            exclusion_reason=exclusion_reason,
        )

    def _group_candidates(self, candidates: Iterable[_Candidate]) -> tuple[_ParentGroup, ...]:
        groups: list[_ParentGroup] = []
        for candidate in candidates:
            if groups and self._can_join(groups[-1], candidate):
                groups[-1].candidates.append(candidate)
                continue
            groups.append(
                _ParentGroup(
                    candidates=[candidate],
                    unit_type=candidate.unit_type,
                    section_path=candidate.section_path,
                    retrieval_eligible=candidate.retrieval_eligible,
                    exclusion_reason=candidate.exclusion_reason,
                )
            )
        return tuple(groups)

    def _can_join(self, group: _ParentGroup, candidate: _Candidate) -> bool:
        previous = group.candidates[-1]
        if (
            group.unit_type is not candidate.unit_type
            or group.section_path != candidate.section_path
            or group.retrieval_eligible != candidate.retrieval_eligible
            or group.exclusion_reason != candidate.exclusion_reason
        ):
            return False
        if candidate.unit_type is ContentUnitType.TABLE:
            return previous.docling_refs == candidate.docling_refs
        if candidate.unit_type in _PROTECTED_UNIT_TYPES:
            return bool(set(previous.docling_refs) & set(candidate.docling_refs)) or (
                _heading_declares_unit(group.section_path, candidate.unit_type)
            )
        parent_text = "\n\n".join(
            [*(part.display_text for part in group.candidates), candidate.display_text]
        )
        return self.tokenizer.count_tokens(parent_text) <= self.config.parent_soft_tokens

    def _make_parent(
        self,
        document: DoclingDocument,
        local_id: str,
        sequence_number: int,
        group: _ParentGroup,
    ) -> ExtractedContentUnit:
        structured_content: dict[str, object] | None = None
        display_format = DisplayFormat.PLAIN_TEXT
        if group.unit_type is ContentUnitType.TABLE:
            table = group.candidates[0].chunk.meta.doc_items[0]
            if not isinstance(table, TableItem):
                raise ValueError("table candidate did not retain its native TableItem")
            display_text = table.export_to_markdown(document).strip()
            display_format = DisplayFormat.MARKDOWN
            structured_content = table.data.model_dump(mode="json")
        else:
            display_text = "\n\n".join(
                candidate.display_text for candidate in group.candidates
            ).strip()
        page_indexes = tuple(
            sorted({page for candidate in group.candidates for page in candidate.page_indexes})
        )
        docling_refs = tuple(
            dict.fromkeys(ref for candidate in group.candidates for ref in candidate.docling_refs)
        )
        provenance: dict[str, object] = {
            "children": [candidate.provenance for candidate in group.candidates],
        }
        checksum_value = {
            "display_format": display_format.value,
            "display_text": display_text,
            "structured_content": structured_content,
        }
        return ExtractedContentUnit(
            local_id=local_id,
            sequence_number=sequence_number,
            unit_type=group.unit_type,
            display_text=display_text,
            display_format=display_format,
            structured_content=structured_content,
            section_path=group.section_path,
            retrieval_eligible=group.retrieval_eligible,
            exclusion_reason=group.exclusion_reason,
            content_sha256=_json_sha256(checksum_value),
            page_indexes=page_indexes,
            docling_refs=docling_refs,
            provenance=provenance,
        )


def _classify_unit(
    section_path: tuple[str, ...], display_text: str, labels: tuple[str, ...]
) -> ContentUnitType:
    if DocItemLabel.TABLE.value in labels:
        return ContentUnitType.TABLE
    if labels and set(labels) <= {DocItemLabel.LIST_ITEM.value}:
        return ContentUnitType.LIST
    if labels and set(labels) <= {DocItemLabel.CAPTION.value}:
        return ContentUnitType.CAPTION
    semantic_label = section_path[-1] if section_path else display_text
    for pattern, unit_type in (
        (_DEFINITION, ContentUnitType.DEFINITION),
        (_LAW, ContentUnitType.LAW),
        (_EXAMPLE, ContentUnitType.SOLVED_EXAMPLE),
        (_ACTIVITY, ContentUnitType.ACTIVITY),
    ):
        if pattern.match(semantic_label.strip()) or pattern.match(display_text.strip()):
            return unit_type
    return ContentUnitType.PROSE


def _classify_content(labels: tuple[str, ...]) -> ChunkContentType:
    values = set(labels)
    if values == {DocItemLabel.TABLE.value}:
        return ChunkContentType.TABLE
    if values == {DocItemLabel.LIST_ITEM.value}:
        return ChunkContentType.LIST
    if values == {DocItemLabel.CAPTION.value}:
        return ChunkContentType.CAPTION
    if values <= {DocItemLabel.TITLE.value, DocItemLabel.SECTION_HEADER.value}:
        return ChunkContentType.HEADING
    if values <= {
        DocItemLabel.TEXT.value,
        DocItemLabel.PARAGRAPH.value,
        DocItemLabel.PAGE_HEADER.value,
        DocItemLabel.PAGE_FOOTER.value,
    }:
        return ChunkContentType.PROSE
    return ChunkContentType.MIXED


def _heading_declares_unit(
    section_path: tuple[str, ...], unit_type: ContentUnitType
) -> bool:
    if not section_path:
        return False
    heading = section_path[-1].strip()
    pattern_by_type = {
        ContentUnitType.DEFINITION: _DEFINITION,
        ContentUnitType.LAW: _LAW,
        ContentUnitType.SOLVED_EXAMPLE: _EXAMPLE,
        ContentUnitType.ACTIVITY: _ACTIVITY,
    }
    pattern = pattern_by_type.get(unit_type)
    return pattern is not None and pattern.match(heading) is not None


def _exclusion_reason(labels: tuple[str, ...], display_text: str) -> str | None:
    if labels and set(labels) <= _NOISE_LABELS:
        return "explicit_page_margin_label"
    if _INDD_MARKER.fullmatch(display_text.strip()):
        return "indd_export_marker"
    return None


def _provenance(chunk: DocChunk) -> dict[str, object]:
    return {
        "doc_items": [
            {
                "self_ref": item.self_ref,
                "label": item.label.value,
                "locations": [
                    {
                        "page_index": provenance.page_no - 1,
                        "bbox": provenance.bbox.model_dump(mode="json"),
                        "char_span": list(provenance.charspan),
                    }
                    for provenance in item.prov
                ],
            }
            for item in chunk.meta.doc_items
        ]
    }


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return _text_sha256(payload)
