"""Immutable contracts shared by RAG orchestration and application adapters."""

from enum import IntEnum, StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

QueryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
]
DisplayText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
CitationId = Annotated[
    str,
    StringConstraints(pattern=r"^T[1-9][0-9]*$"),
]


class ContractModel(BaseModel):
    """Base configuration for immutable, closed domain contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TextbookStandard(IntEnum):
    """Supported Tamil Nadu State Board standards for the MVP."""

    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10


class AnswerMode(StrEnum):
    """Policies controlling how generated explanations may use knowledge."""

    TEXTBOOK_ONLY = "textbook_only"
    TEXTBOOK_PLUS_GENERAL = "textbook_plus_general"


class EvidenceInclusionReason(StrEnum):
    """Reason an evidence item was selected for generation context."""

    SEMANTIC_MATCH = "semantic_match"
    NEIGHBOR = "neighbor"
    STRUCTURAL_PARENT = "structural_parent"


class SearchFilters(ContractModel):
    """Optional textbook metadata constraints applied during retrieval."""

    standards: tuple[TextbookStandard, ...] = ()
    subjects: tuple[DisplayText, ...] = ()
    book_ids: tuple[UUID, ...] = ()
    document_ids: tuple[UUID, ...] = ()


class SearchRequest(ContractModel):
    """Provider-neutral semantic retrieval request."""

    query: QueryText
    top_k: int = Field(default=10, ge=1, le=50)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class Evidence(ContractModel):
    """Textbook chunk with enough provenance to produce a real citation."""

    chunk_id: UUID
    document_id: UUID
    book_id: UUID
    book_title: DisplayText
    edition: DisplayText | None = None
    standard: TextbookStandard
    subject: DisplayText
    pdf_page_index: int = Field(ge=0)
    printed_page_label: DisplayText | None = None
    section_path: tuple[DisplayText, ...] = ()
    text: DisplayText
    asset_ids: tuple[UUID, ...] = ()


class SearchHit(ContractModel):
    """Ranked evidence returned by a retriever implementation."""

    rank: int = Field(ge=1)
    score: float = Field(allow_inf_nan=False)
    evidence: Evidence


class SearchResult(ContractModel):
    """Validated ranked result set for one semantic-search request."""

    request: SearchRequest
    hits: tuple[SearchHit, ...] = ()

    @model_validator(mode="after")
    def validate_ranking(self) -> Self:
        """Require bounded, contiguous ranks with no duplicate chunks."""
        if len(self.hits) > self.request.top_k:
            msg = "search result contains more hits than requested"
            raise ValueError(msg)

        ranks = tuple(hit.rank for hit in self.hits)
        if ranks != tuple(range(1, len(self.hits) + 1)):
            msg = "search hit ranks must be contiguous and start at one"
            raise ValueError(msg)

        chunk_ids = tuple(hit.evidence.chunk_id for hit in self.hits)
        if len(chunk_ids) != len(set(chunk_ids)):
            msg = "search result cannot contain duplicate chunks"
            raise ValueError(msg)
        return self


class AnswerRequest(ContractModel):
    """Request for retrieval followed by an answer-generation workflow."""

    search: SearchRequest
    mode: AnswerMode = AnswerMode.TEXTBOOK_ONLY


class EvidenceItem(ContractModel):
    """Evidence selected for generation and assigned a stable citation label."""

    citation_id: CitationId
    evidence: Evidence
    inclusion_reason: EvidenceInclusionReason


class EvidencePack(ContractModel):
    """Bounded provider-neutral context passed to an answer generator."""

    query: QueryText
    mode: AnswerMode
    items: tuple[EvidenceItem, ...] = ()
    estimated_tokens: int = Field(default=0, ge=0)


class GenerationRequest(ContractModel):
    """Structured input accepted by any answer-generator adapter."""

    evidence_pack: EvidencePack


class GenerationResult(ContractModel):
    """Provider-neutral structured output returned by answer generation."""

    answer: DisplayText
    citation_ids: tuple[CitationId, ...] = ()
    supplementary_explanation: DisplayText | None = None
    abstained: bool = False
