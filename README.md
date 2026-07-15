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

Create a local configuration file from the safe development template:

```shell
cp .env.example .env
```

All backend environment variables use the `TNPSC_` prefix. Provider keys are optional and the
committed templates contain no credentials. Tests construct isolated settings and do not load a
developer's `.env` file.

The API emits guarded structlog JSON events and OpenTelemetry server spans. Traces remain
in-process unless `TNPSC_OTEL_TRACES_ENDPOINT` points to an OTLP/HTTP collector. The logging
processor accepts only stable event names and an explicit metadata allowlist; unstructured messages
are redacted. Request bodies, query strings, textbook content, prompts, evidence, model output, and
exception messages are excluded by default.

Successful `/health/live`, future `/health/ready`, and `/metrics` requests receive request IDs but do
not emit access events or spans. Failures on those routes still emit a structured failure event.
Response-decorating middleware such as CORS must wrap the observability boundary. An exception is
converted to the generic JSON 500 only before response headers start; a later streaming exception is
recorded and re-raised so the application never sends a second response start.

Correlation context follows ordinary async tasks. Blocking thread work must use
`run_in_thread_with_context`; raw executors are not an approved application boundary. Queued workers
must use `inject_worker_context` and `extract_worker_context` to carry W3C `traceparent` plus only the
approved request, document, ingestion-run, and stage identifiers. A live Python context object is
never serialized. When the worker is implemented, delayed or retryable jobs should use span links
instead of implying one long synchronous parent/child operation.

Run the quality gates:

```shell
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pyrefly check
uv run pytest
```

Run the FastAPI development server:

```shell
uv run fastapi dev src/tnpsc_book_rag/main.py
```

The initial liveness endpoint is available at `GET /health/live`.
