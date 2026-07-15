# TNPSC Book RAG

An English-first retrieval-augmented generation system for Tamil Nadu State Board textbooks.
The implementation follows the phased roadmap in [`plan.md`](plan.md), beginning with a
FastAPI backend for trustworthy PDF extraction and page-level provenance. A SvelteKit frontend
will be added after the backend MVP is usable.

## Repository layout

- `backend/` contains the Python, FastAPI, Docling, retrieval, and generation services.
- `frontend/` is reserved for the future SvelteKit and shadcn-svelte application.
- `plan.md` defines the phased implementation and production-readiness roadmap.

## Current status

Phase 0 foundation work is in progress. No ingestion, retrieval, or answer-generation API is
available yet.

## Development

Prerequisites:

- Python 3.13, managed by `uv`
- `uv`
- Docker with Compose (required by the database phase)

Run backend commands from `backend/`:

```shell
cd backend
uv sync --all-groups
```

Run the quality gates:

```shell
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pyrefly check --summarize-errors
uv run pytest
```

Run the FastAPI development server:

```shell
uv run fastapi dev src/tnpsc_book_rag/main.py
```

The initial liveness endpoint is available at `GET /health/live`.
