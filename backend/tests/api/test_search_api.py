"""Contract tests for search and answer generation API routes (Phases 2-4)."""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient

from tnpsc_book_rag.api.answer_service import AnswerResult
from tnpsc_book_rag.api.search_routes import create_search_router
from tnpsc_rag.models import (
    AnswerRequest,
    Evidence,
    EvidenceInclusionReason,
    EvidenceItem,
    EvidencePack,
    GenerationResult,
    SearchHit,
    SearchRequest,
    SearchResult,
    TextbookStandard,
)

# --- Helpers ---


def _evidence(text: str = "Pressure is force per unit area.") -> Evidence:
    return Evidence(
        chunk_id=uuid4(),
        document_id=uuid4(),
        book_id=uuid4(),
        book_title="Standard 6 Science",
        edition="Term I",
        standard=TextbookStandard.SIX,
        subject="Science",
        pdf_page_index=0,
        printed_page_label="1",
        section_path=("Force and Pressure", "Definition"),
        text=text,
    )


def _search_hit(rank: int = 1, score: float = 0.92) -> SearchHit:
    return SearchHit(rank=rank, score=score, evidence=_evidence())


class MockSearchService:
    """Mock search service returning canned results."""

    def __init__(self, hits: list[SearchHit] | None = None) -> None:
        self._hits = hits or [_search_hit()]

    async def search(self, request: SearchRequest) -> SearchResult:
        return SearchResult(request=request, hits=tuple(self._hits))


class MockAnswerService:
    """Mock answer service returning canned results."""

    def __init__(self, abstained: bool = False) -> None:
        self._abstained = abstained

    async def answer(self, request: AnswerRequest) -> AnswerResult:
        evidence = _evidence()
        hit = SearchHit(rank=1, score=0.92, evidence=evidence)
        search_result = SearchResult(request=request.search, hits=(hit,))
        evidence_pack = EvidencePack(
            query=request.search.query,
            mode=request.mode,
            items=(
                EvidenceItem(
                    citation_id="T1",
                    evidence=evidence,
                    inclusion_reason=EvidenceInclusionReason.SEMANTIC_MATCH,
                ),
            ),
            estimated_tokens=50,
        )
        generation = GenerationResult(
            answer="Pressure is force acting per unit area."
            if not self._abstained
            else "Insufficient evidence.",
            citation_ids=() if self._abstained else ("T1",),
            supplementary_explanation=None,
            abstained=self._abstained,
        )
        return AnswerResult(
            search_result=search_result,
            evidence_pack=evidence_pack,
            generation=generation,
        )


def _app(search_service=None, answer_service=None) -> FastAPI:
    """Build a minimal app with only the search router for isolated testing."""
    from tnpsc_book_rag.api.errors import install_exception_handlers

    app = FastAPI(title="test")
    install_exception_handlers(app)
    router = create_search_router(search_service, answer_service)
    app.include_router(router)
    return app


# --- Search endpoint tests ---


class TestSearchEndpoint:
    @pytest.mark.anyio
    async def test_search_returns_results(self) -> None:
        app = _app(search_service=MockSearchService())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/search",
                json={"query": "What is pressure?", "top_k": 5},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["query"] == "What is pressure?"
        assert payload["top_k"] == 5
        assert len(payload["results"]) == 1
        hit = payload["results"][0]
        assert hit["rank"] == 1
        assert hit["score"] == 0.92
        assert hit["evidence"]["book_title"] == "Standard 6 Science"
        assert hit["evidence"]["standard"] == 6

    @pytest.mark.anyio
    async def test_search_requires_query(self) -> None:
        app = _app(search_service=MockSearchService())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/v1/search", json={"query": ""})

        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_search_unavailable_returns_503(self) -> None:
        app = _app(search_service=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/search", json={"query": "test query"}
            )

        assert response.status_code == 503

    @pytest.mark.anyio
    async def test_search_with_filters(self) -> None:
        app = _app(search_service=MockSearchService())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/search",
                json={
                    "query": "What is pressure?",
                    "top_k": 5,
                    "filters": {"standards": [6], "subjects": ["Science"]},
                },
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["filters"]["standards"] == [6]
        assert payload["filters"]["subjects"] == ["Science"]


# --- Answer endpoint tests ---


class TestAnswerEndpoint:
    @pytest.mark.anyio
    async def test_answer_returns_structured_response(self) -> None:
        app = _app(answer_service=MockAnswerService())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/answers",
                json={
                    "query": "What is pressure?",
                    "mode": "textbook_only",
                    "top_k": 5,
                },
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["query"] == "What is pressure?"
        assert payload["mode"] == "textbook_only"
        assert payload["textbook"]["status"] == "answered"
        assert len(payload["textbook"]["blocks"]) > 0
        assert len(payload["textbook"]["citations"]) == 1
        assert payload["textbook"]["citations"][0]["citation_id"] == "T1"
        assert "answer_id" in payload
        assert "request_id" in payload

    @pytest.mark.anyio
    async def test_answer_abstained_returns_insufficient_evidence(self) -> None:
        app = _app(answer_service=MockAnswerService(abstained=True))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/answers",
                json={
                    "query": "What is quantum gravity?",
                    "mode": "textbook_only",
                },
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["textbook"]["status"] == "insufficient_evidence"
        assert payload["textbook"]["citations"] == []

    @pytest.mark.anyio
    async def test_answer_unavailable_returns_503(self) -> None:
        app = _app(answer_service=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/answers",
                json={"query": "test", "mode": "textbook_only"},
            )

        assert response.status_code == 503

    @pytest.mark.anyio
    async def test_answer_requires_valid_mode(self) -> None:
        app = _app(answer_service=MockAnswerService())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/answers",
                json={"query": "test", "mode": "invalid_mode"},
            )

        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_answer_sse_streaming(self) -> None:
        app = _app(answer_service=MockAnswerService())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/answers",
                json={"query": "What is pressure?", "mode": "textbook_only"},
                headers={"Accept": "text/event-stream"},
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = response.text
        assert "event: answer.started" in body
        assert "event: answer.progress" in body
        assert "event: answer.completed" in body
