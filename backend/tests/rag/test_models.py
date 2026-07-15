"""Tests for provider-neutral RAG domain contracts."""

from collections.abc import Callable
from uuid import UUID

import pytest
from pydantic import ValidationError

from tnpsc_rag import (
    AnswerMode,
    AnswerRequest,
    Evidence,
    EvidenceInclusionReason,
    EvidenceItem,
    EvidencePack,
    GenerationRequest,
    GenerationResult,
    SearchFilters,
    SearchHit,
    SearchRequest,
    SearchResult,
    TextbookStandard,
)


def make_evidence(*, chunk_number: int = 1) -> Evidence:
    """Build deterministic textbook evidence for contract tests."""
    return Evidence(
        chunk_id=UUID(int=chunk_number),
        document_id=UUID(int=100),
        book_id=UUID(int=200),
        book_title="Social Science, Standard 6",
        edition="2025",
        standard=TextbookStandard.SIX,
        subject="Social Science",
        pdf_page_index=11,
        printed_page_label="4",
        section_path=("History", "What is History?"),
        text="History is the study of past events.",
    )


def make_hit(*, rank: int, chunk_number: int) -> SearchHit:
    """Build one ranked search hit."""
    return SearchHit(
        rank=rank,
        score=1.0 / rank,
        evidence=make_evidence(chunk_number=chunk_number),
    )


def test_search_request_is_typed_and_immutable() -> None:
    """Search input is normalized and rejects undeclared application fields."""
    request = SearchRequest(
        query="  what is history?  ",
        filters=SearchFilters(
            standards=(TextbookStandard.SIX,),
            subjects=("Social Science",),
        ),
    )

    assert request.query == "what is history?"
    assert request.filters.standards == (TextbookStandard.SIX,)

    with pytest.raises(ValidationError):
        SearchRequest.model_validate({"query": "history", "provider": "pgvector"})

    with pytest.raises(ValidationError):
        request.__setattr__("top_k", 5)


def test_search_result_accepts_contiguous_unique_hits() -> None:
    """A valid retriever result preserves deterministic rank order."""
    request = SearchRequest(query="history", top_k=2)
    result = SearchResult(
        request=request,
        hits=(
            make_hit(rank=1, chunk_number=1),
            make_hit(rank=2, chunk_number=2),
        ),
    )

    assert tuple(hit.rank for hit in result.hits) == (1, 2)


@pytest.mark.parametrize(
    ("build_result", "expected_message"),
    [
        (
            lambda: SearchResult(
                request=SearchRequest(query="history", top_k=1),
                hits=(
                    make_hit(rank=1, chunk_number=1),
                    make_hit(rank=2, chunk_number=2),
                ),
            ),
            "more hits than requested",
        ),
        (
            lambda: SearchResult(
                request=SearchRequest(query="history"),
                hits=(make_hit(rank=2, chunk_number=1),),
            ),
            "ranks must be contiguous",
        ),
        (
            lambda: SearchResult(
                request=SearchRequest(query="history"),
                hits=(
                    make_hit(rank=1, chunk_number=1),
                    make_hit(rank=2, chunk_number=1),
                ),
            ),
            "duplicate chunks",
        ),
    ],
)
def test_search_result_rejects_invalid_rankings(
    build_result: Callable[[], SearchResult],
    expected_message: str,
) -> None:
    """Retriever adapters cannot return malformed ranking data."""
    with pytest.raises(ValidationError, match=expected_message):
        build_result()


def test_generation_contract_uses_an_explicit_evidence_pack() -> None:
    """Generation consumes selected evidence rather than performing retrieval."""
    evidence = make_evidence()
    pack = EvidencePack(
        query="what is history?",
        mode=AnswerMode.TEXTBOOK_ONLY,
        items=(
            EvidenceItem(
                citation_id="T1",
                evidence=evidence,
                inclusion_reason=EvidenceInclusionReason.SEMANTIC_MATCH,
            ),
        ),
        estimated_tokens=12,
    )
    answer_request = AnswerRequest(
        search=SearchRequest(query=pack.query),
        mode=pack.mode,
    )
    generation_request = GenerationRequest(evidence_pack=pack)
    result = GenerationResult(
        answer="History is the study of past events.",
        citation_ids=("T1",),
    )

    assert answer_request.mode is AnswerMode.TEXTBOOK_ONLY
    assert generation_request.evidence_pack.items[0].evidence == evidence
    assert result.citation_ids == ("T1",)


def test_citation_ids_use_stable_textbook_labels() -> None:
    """Malformed model-generated citation labels fail validation."""
    with pytest.raises(ValidationError):
        GenerationResult(
            answer="History is the study of past events.",
            citation_ids=("page four",),
        )
