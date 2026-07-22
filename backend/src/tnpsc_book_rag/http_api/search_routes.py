"""Search and answer generation API routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from tnpsc_rag.models import (
    AnswerMode,
    AnswerRequest,
    SearchFilters,
    SearchRequest,
    TextbookStandard,
)

_LOGGER = structlog.stdlib.get_logger(__name__)


# --- Request/Response Schemas ---


class SearchRequestSchema(BaseModel):
    """Search request matching the API spec."""

    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=1, max_length=1000)]
    top_k: int = Field(default=10, ge=1, le=50)
    filters: SearchFiltersSchema | None = None


class SearchFiltersSchema(BaseModel):
    """Optional search filters."""

    model_config = ConfigDict(extra="forbid")

    standards: list[int] = Field(default_factory=list, max_length=5)
    subjects: list[str] = Field(default_factory=list, max_length=20)
    book_ids: list[UUID] = Field(default_factory=list, max_length=50)
    document_ids: list[UUID] = Field(default_factory=list, max_length=50)


class EvidenceAssetSchema(BaseModel):
    """Asset reference in search results."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    asset_type: str
    caption: str | None = None
    alt_text: str | None = None
    alt_text_source: str | None = None
    is_decorative: bool = False
    pixel_width: int | None = None
    pixel_height: int | None = None
    content_url: str
    thumbnail_url: str | None = None
    thumbnail_pixel_width: int | None = None
    thumbnail_pixel_height: int | None = None


class EvidenceSchema(BaseModel):
    """Evidence record in search results."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    page_id: UUID | None = None
    document_id: UUID
    book_id: UUID
    book_title: str
    edition: str | None = None
    standard: int
    subject: str
    pdf_page_index: int
    printed_page_label: str | None = None
    section_path: list[str] = Field(default_factory=list)
    content_type: str = "prose"
    text: str
    assets: list[EvidenceAssetSchema] = Field(default_factory=list)
    source_url: str


class SearchHitSchema(BaseModel):
    """One ranked search result."""

    model_config = ConfigDict(extra="forbid")

    rank: int
    score: float
    score_kind: Literal["cosine_similarity"] = "cosine_similarity"
    evidence: EvidenceSchema


class SearchResponseSchema(BaseModel):
    """Search response matching the API spec."""

    model_config = ConfigDict(extra="forbid")

    query: str
    top_k: int
    filters: SearchFiltersSchema
    results: list[SearchHitSchema] = Field(default_factory=list)


# --- Answer Schemas ---


class AnswerRequestSchema(BaseModel):
    """Answer generation request."""

    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=1, max_length=1000)]
    mode: Literal["textbook_only", "textbook_plus_general"]
    top_k: int = Field(default=10, ge=1, le=50)
    response_length: Literal["short", "medium", "long"] = "medium"
    filters: SearchFiltersSchema | None = None


class TextNodeSchema(BaseModel):
    """Text inline node."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["text"] = "text"
    content: str


class CitationNodeSchema(BaseModel):
    """Citation inline node."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["citation"] = "citation"
    citation_id: str
    fallback_text: str


class ParagraphBlockSchema(BaseModel):
    """Paragraph block with inline nodes."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["paragraph"] = "paragraph"
    nodes: list[TextNodeSchema | CitationNodeSchema]


class BulletListBlockSchema(BaseModel):
    """Bullet list block."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["bullet_list"] = "bullet_list"
    items: list[list[TextNodeSchema | CitationNodeSchema]]


class CitationSchema(BaseModel):
    """Citation evidence record."""

    model_config = ConfigDict(extra="forbid")

    citation_id: str
    chunk_id: UUID
    page_id: UUID | None = None
    document_id: UUID
    book_id: UUID
    book_title: str
    edition: str | None = None
    standard: int
    subject: str
    pdf_page_index: int
    printed_page_label: str | None = None
    section_path: list[str] = Field(default_factory=list)
    content_type: str = "prose"
    text: str
    assets: list[EvidenceAssetSchema] = Field(default_factory=list)
    source_url: str


class TextbookAnswerSchema(BaseModel):
    """Textbook answer section."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["answered", "insufficient_evidence"]
    blocks: list[ParagraphBlockSchema | BulletListBlockSchema]
    citations: list[CitationSchema]


class SupplementarySchema(BaseModel):
    """Supplementary general knowledge section."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["general_knowledge"] = "general_knowledge"
    blocks: list[ParagraphBlockSchema | BulletListBlockSchema]


class AnswerResponseSchema(BaseModel):
    """Answer generation response."""

    model_config = ConfigDict(extra="forbid")

    answer_id: UUID
    query: str
    mode: str
    textbook: TextbookAnswerSchema
    supplementary: SupplementarySchema | None = None
    request_id: UUID
    created_at: str


# --- Protocol for search/answer services ---


class SearchService(Protocol):
    """Search service protocol."""

    async def search(self, request: SearchRequest) -> Any: ...


class AnswerService(Protocol):
    """Answer service protocol."""

    async def answer(self, request: AnswerRequest) -> Any: ...


# --- Route Factory ---


def create_search_router(
    search_service: SearchService | None,
    answer_service: AnswerService | None,
) -> APIRouter:
    """Create the search and answer router."""
    router = APIRouter(prefix="/v1", tags=["search"])

    @router.post(
        "/search",
        response_model=SearchResponseSchema,
        status_code=status.HTTP_200_OK,
    )
    async def search(request_body: SearchRequestSchema) -> SearchResponseSchema:
        """Semantic search over the textbook corpus."""
        if search_service is None:
            from tnpsc_book_rag.http_api.errors import ApiProblem

            raise ApiProblem(
                status=503,
                code="search_unavailable",
                title="Search unavailable",
                detail="Semantic search is not configured.",
            )

        # Convert API schema to domain model
        filters = SearchFilters(
            standards=tuple(
                TextbookStandard(s)
                for s in (request_body.filters.standards if request_body.filters else [])
            ),
            subjects=tuple(request_body.filters.subjects if request_body.filters else []),
            book_ids=tuple(request_body.filters.book_ids if request_body.filters else []),
            document_ids=tuple(request_body.filters.document_ids if request_body.filters else []),
        )

        domain_request = SearchRequest(
            query=request_body.query.strip(),
            top_k=request_body.top_k,
            filters=filters,
        )

        result = await search_service.search(domain_request)

        # Convert domain result to API schema
        hits = []
        for hit in result.hits:
            evidence = hit.evidence
            hits.append(
                SearchHitSchema(
                    rank=hit.rank,
                    score=hit.score,
                    evidence=EvidenceSchema(
                        chunk_id=evidence.chunk_id,
                        document_id=evidence.document_id,
                        book_id=evidence.book_id,
                        book_title=evidence.book_title,
                        edition=evidence.edition,
                        standard=int(evidence.standard),
                        subject=evidence.subject,
                        pdf_page_index=evidence.pdf_page_index,
                        printed_page_label=evidence.printed_page_label,
                        section_path=list(evidence.section_path),
                        text=evidence.text,
                        source_url=f"/v1/sources/{evidence.chunk_id}",
                    ),
                )
            )

        return SearchResponseSchema(
            query=request_body.query,
            top_k=request_body.top_k,
            filters=request_body.filters or SearchFiltersSchema(),
            results=hits,
        )

    @router.post(
        "/answers",
        response_model=AnswerResponseSchema,
        status_code=status.HTTP_200_OK,
    )
    async def create_answer(
        request_body: AnswerRequestSchema,
        request: Request,
    ) -> Response:
        """Generate an answer from textbook evidence."""
        # Check if client wants SSE streaming
        accept = request.headers.get("accept", "")
        wants_stream = "text/event-stream" in accept

        if answer_service is None:
            from tnpsc_book_rag.http_api.errors import ApiProblem

            raise ApiProblem(
                status=503,
                code="generation_unavailable",
                title="Generation unavailable",
                detail="Answer generation is not configured.",
            )

        # Convert API schema to domain model
        filters = SearchFilters(
            standards=tuple(
                TextbookStandard(s)
                for s in (request_body.filters.standards if request_body.filters else [])
            ),
            subjects=tuple(request_body.filters.subjects if request_body.filters else []),
            book_ids=tuple(request_body.filters.book_ids if request_body.filters else []),
            document_ids=tuple(request_body.filters.document_ids if request_body.filters else []),
        )

        search_request = SearchRequest(
            query=request_body.query.strip(),
            top_k=request_body.top_k,
            filters=filters,
        )

        domain_request = AnswerRequest(
            search=search_request,
            mode=AnswerMode(request_body.mode),
        )

        answer_id = uuid4()
        request_id = uuid4()

        if wants_stream:
            return await _stream_answer(
                answer_service, domain_request, answer_id, request_id, request_body
            )

        # Synchronous response
        result = await answer_service.answer(domain_request)
        return _build_answer_response(result, answer_id, request_id, request_body)

    return router


async def _stream_answer(
    answer_service: AnswerService,
    request: AnswerRequest,
    answer_id: UUID,
    request_id: UUID,
    request_body: AnswerRequestSchema,
) -> StreamingResponse:
    """Stream answer generation progress via SSE."""

    async def event_generator():
        event_id = 0

        # Send started event
        event_id += 1
        started_data = json.dumps(
            {"answer_id": str(answer_id), "request_id": str(request_id)}
        )
        yield f"event: answer.started\nid: {event_id}\ndata: {started_data}\n\n"

        # Send progress events
        event_id += 1
        retrieval_data = json.dumps(
            {"answer_id": str(answer_id), "stage": "retrieval"}
        )
        yield f"event: answer.progress\nid: {event_id}\ndata: {retrieval_data}\n\n"

        event_id += 1
        generation_data = json.dumps(
            {"answer_id": str(answer_id), "stage": "generation"}
        )
        yield f"event: answer.progress\nid: {event_id}\ndata: {generation_data}\n\n"

        # Generate the answer
        result = await answer_service.answer(request)

        # Build and send completed event
        response = _build_answer_response(result, answer_id, request_id, request_body)
        event_id += 1
        yield f"event: answer.completed\nid: {event_id}\ndata: {response.model_dump_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _build_answer_response(
    result: Any,
    answer_id: UUID,
    request_id: UUID,
    request_body: AnswerRequestSchema,
) -> AnswerResponseSchema:
    """Build the answer response schema from generation result."""
    # Build citation list from evidence pack
    citations = []
    citation_nodes = []

    if hasattr(result, "evidence_pack") and result.evidence_pack:
        for item in result.evidence_pack.items:
            ev = item.evidence
            citations.append(
                CitationSchema(
                    citation_id=item.citation_id,
                    chunk_id=ev.chunk_id,
                    document_id=ev.document_id,
                    book_id=ev.book_id,
                    book_title=ev.book_title,
                    edition=ev.edition,
                    standard=int(ev.standard),
                    subject=ev.subject,
                    pdf_page_index=ev.pdf_page_index,
                    printed_page_label=ev.printed_page_label,
                    section_path=list(ev.section_path),
                    text=ev.text,
                    source_url=f"/v1/sources/{ev.chunk_id}",
                )
            )
            citation_nodes.append(
                CitationNodeSchema(
                    citation_id=item.citation_id,
                    fallback_text=f"[{item.citation_id}]",
                )
            )

    # Build answer blocks
    generation = result.generation if hasattr(result, "generation") else result
    answer_text = generation.answer if hasattr(generation, "answer") else str(generation)
    abstained = generation.abstained if hasattr(generation, "abstained") else False

    if abstained:
        blocks = [ParagraphBlockSchema(nodes=[TextNodeSchema(content=answer_text)])]
        textbook_status = "insufficient_evidence"
        citations = []
    else:
        # Build nodes with text and citations
        nodes: list[TextNodeSchema | CitationNodeSchema] = [
            TextNodeSchema(content=answer_text + " ")
        ]
        # Add citation references
        for cid in generation.citation_ids if hasattr(generation, "citation_ids") else []:
            nodes.append(CitationNodeSchema(citation_id=cid, fallback_text=f"[{cid}]"))
        blocks = [ParagraphBlockSchema(nodes=nodes)]
        textbook_status = "answered"

    # Build supplementary section
    supplementary = None
    supp_text = (
        generation.supplementary_explanation
        if hasattr(generation, "supplementary_explanation")
        else None
    )
    if supp_text and request_body.mode == "textbook_plus_general":
        supplementary = SupplementarySchema(
            blocks=[ParagraphBlockSchema(nodes=[TextNodeSchema(content=supp_text)])]
        )

    return AnswerResponseSchema(
        answer_id=answer_id,
        query=request_body.query,
        mode=request_body.mode,
        textbook=TextbookAnswerSchema(
            status=textbook_status,  # type: ignore[arg-type]
            blocks=blocks,
            citations=citations,
        ),
        supplementary=supplementary,
        request_id=request_id,
        created_at=datetime.now(UTC).isoformat(),
    )
