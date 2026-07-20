"""Tests for Phase 2-4 adapters: embeddings, context assembly, generation, orchestrator."""

from uuid import uuid4

import pytest

from tnpsc_book_rag.adapters.context import EvidenceContextAssembler
from tnpsc_book_rag.adapters.embeddings import EMBEDDING_DIMENSION, EmbeddingBatch
from tnpsc_book_rag.adapters.generation import PydanticAIGenerator, StructuredAnswer
from tnpsc_rag.models import (
    AnswerMode,
    AnswerRequest,
    Evidence,
    EvidenceInclusionReason,
    EvidencePack,
    GenerationRequest,
    GenerationResult,
    SearchHit,
    SearchRequest,
    SearchResult,
    TextbookStandard,
)

# --- Helpers ---


def _evidence(text: str = "Pressure is force per unit area.", **kwargs) -> Evidence:
    defaults = {
        "chunk_id": uuid4(),
        "document_id": uuid4(),
        "book_id": uuid4(),
        "book_title": "Standard 6 Science",
        "edition": "Term I",
        "standard": TextbookStandard.SIX,
        "subject": "Science",
        "pdf_page_index": 0,
        "printed_page_label": "1",
        "section_path": ("Force and Pressure", "Definition"),
        "text": text,
    }
    defaults.update(kwargs)
    return Evidence(**defaults)


def _hit(rank: int, score: float, text: str = "Pressure is force per unit area.") -> SearchHit:
    return SearchHit(rank=rank, score=score, evidence=_evidence(text=text))


def _search_request(query: str = "What is pressure?", top_k: int = 10) -> SearchRequest:
    return SearchRequest(query=query, top_k=top_k)


def _search_result(hits: list[SearchHit], query: str = "What is pressure?") -> SearchResult:
    return SearchResult(request=_search_request(query), hits=tuple(hits))


def _answer_request(query: str = "What is pressure?") -> AnswerRequest:
    return AnswerRequest(search=_search_request(query), mode=AnswerMode.TEXTBOOK_ONLY)


# --- Phase 2: Embedding model contract ---


class TestEmbeddingBatchContract:
    def test_empty_batch_has_correct_metadata(self) -> None:
        batch = EmbeddingBatch(
            model_identifier="BAAI/bge-small-en-v1.5",
            model_revision="abc123",
            dimension=EMBEDDING_DIMENSION,
            vectors=[],
            content_checksums=[],
        )
        assert batch.dimension == 384
        assert batch.vectors == []
        assert batch.content_checksums == []

    def test_batch_with_vectors(self) -> None:
        vec = [0.1] * EMBEDDING_DIMENSION
        batch = EmbeddingBatch(
            model_identifier="BAAI/bge-small-en-v1.5",
            model_revision="abc123",
            dimension=EMBEDDING_DIMENSION,
            vectors=[vec],
            content_checksums=["a" * 64],
        )
        assert len(batch.vectors) == 1
        assert len(batch.vectors[0]) == EMBEDDING_DIMENSION


# --- Phase 3: Context assembly ---


class TestEvidenceContextAssembler:
    def test_empty_hits_returns_empty_pack(self) -> None:
        assembler = EvidenceContextAssembler(token_budget=3000)
        request = _answer_request()
        result = _search_result([])

        pack = assembler.assemble(request, result)

        assert pack.items == ()
        assert pack.estimated_tokens == 0
        assert pack.query == "What is pressure?"
        assert pack.mode == AnswerMode.TEXTBOOK_ONLY

    def test_single_hit_gets_citation_t1(self) -> None:
        assembler = EvidenceContextAssembler(token_budget=3000)
        request = _answer_request()
        result = _search_result([_hit(1, 0.95)])

        pack = assembler.assemble(request, result)

        assert len(pack.items) == 1
        assert pack.items[0].citation_id == "T1"
        assert pack.items[0].inclusion_reason == EvidenceInclusionReason.SEMANTIC_MATCH

    def test_multiple_hits_get_sequential_citations(self) -> None:
        assembler = EvidenceContextAssembler(token_budget=10000)
        request = _answer_request()
        hits = [_hit(i, 0.9 - i * 0.1, text=f"Evidence text {i}") for i in range(1, 4)]
        result = _search_result(hits)

        pack = assembler.assemble(request, result)

        assert len(pack.items) == 3
        assert [item.citation_id for item in pack.items] == ["T1", "T2", "T3"]

    def test_token_budget_limits_selection(self) -> None:
        # Very small budget: only top hit should be included
        assembler = EvidenceContextAssembler(token_budget=10)
        request = _answer_request()
        long_text = "x" * 500
        hits = [_hit(1, 0.9, text=long_text), _hit(2, 0.8, text=long_text)]
        result = _search_result(hits)

        pack = assembler.assemble(request, result)

        # Should include at least the top hit even if over budget
        assert len(pack.items) == 1
        assert pack.items[0].citation_id == "T1"

    def test_mode_is_preserved_in_pack(self) -> None:
        assembler = EvidenceContextAssembler(token_budget=3000)
        request = AnswerRequest(
            search=_search_request(), mode=AnswerMode.TEXTBOOK_PLUS_GENERAL
        )
        result = _search_result([_hit(1, 0.9)])

        pack = assembler.assemble(request, result)

        assert pack.mode == AnswerMode.TEXTBOOK_PLUS_GENERAL


# --- Phase 4: Generation ---


class TestPydanticAIGenerator:
    @pytest.mark.anyio
    async def test_empty_evidence_returns_abstained(self) -> None:
        generator = PydanticAIGenerator()
        pack = EvidencePack(
            query="What is pressure?",
            mode=AnswerMode.TEXTBOOK_ONLY,
            items=(),
            estimated_tokens=0,
        )
        request = GenerationRequest(evidence_pack=pack)

        result = await generator.generate(request)

        assert result.abstained is True
        assert result.citation_ids == ()
        assert "enough" in result.answer.lower() or "insufficient" in result.answer.lower()

    def test_structured_answer_model_validation(self) -> None:
        answer = StructuredAnswer(
            answer_text="Pressure is force per unit area.",
            citation_ids=["T1", "T2"],
            supplementary_text=None,
            abstained=False,
        )
        assert answer.answer_text == "Pressure is force per unit area."
        assert answer.citation_ids == ["T1", "T2"]
        assert answer.abstained is False

    def test_structured_answer_abstained(self) -> None:
        answer = StructuredAnswer(
            answer_text="Insufficient evidence.",
            citation_ids=[],
            abstained=True,
        )
        assert answer.abstained is True
        assert answer.supplementary_text is None


# --- Phase 4: Answer orchestrator ---


class TestAnswerOrchestrator:
    @pytest.mark.anyio
    async def test_full_pipeline_with_mocks(self) -> None:
        from tnpsc_book_rag.api.answer_service import AnswerOrchestrator, AnswerResult

        # Mock retriever
        class MockRetriever:
            async def search(self, request: SearchRequest) -> SearchResult:
                return _search_result([_hit(1, 0.92)])

        # Mock generator
        class MockGenerator:
            async def generate(self, request: GenerationRequest) -> GenerationResult:
                return GenerationResult(
                    answer="Pressure is force acting per unit area.",
                    citation_ids=("T1",),
                    supplementary_explanation=None,
                    abstained=False,
                )

        assembler = EvidenceContextAssembler(token_budget=3000)
        orchestrator = AnswerOrchestrator(
            retriever=MockRetriever(),
            context_assembler=assembler,
            generator=MockGenerator(),
        )

        request = _answer_request()
        result = await orchestrator.answer(request)

        assert isinstance(result, AnswerResult)
        assert len(result.search_result.hits) == 1
        assert len(result.evidence_pack.items) == 1
        assert result.generation.abstained is False
        assert "Pressure" in result.generation.answer

    @pytest.mark.anyio
    async def test_pipeline_with_no_results_abstains(self) -> None:
        from tnpsc_book_rag.api.answer_service import AnswerOrchestrator

        class EmptyRetriever:
            async def search(self, request: SearchRequest) -> SearchResult:
                return _search_result([])

        assembler = EvidenceContextAssembler(token_budget=3000)
        generator = PydanticAIGenerator()

        orchestrator = AnswerOrchestrator(
            retriever=EmptyRetriever(),
            context_assembler=assembler,
            generator=generator,
        )

        request = _answer_request()
        result = await orchestrator.answer(request)

        assert result.generation.abstained is True
        assert result.evidence_pack.items == ()
