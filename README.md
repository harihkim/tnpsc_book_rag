# TNPSC Book RAG

An English-first retrieval-augmented generation system for Tamil Nadu State Board textbooks.
The implementation follows the phased roadmap in [`plan.md`](plan.md), beginning with a
FastAPI backend for trustworthy PDF extraction and page-level provenance. A SvelteKit frontend can
develop in parallel against the frozen API contract and its mock shapes.

The frozen frontend-facing API v1 contract is documented in [`api_spec.md`](api_spec.md), with
[`openapi.v1.yaml`](openapi.v1.yaml) as the machine-readable source for generated frontend types
and mocks. Implementation-status markers distinguish the live health probes from planned routes.

## Repository layout

- `backend/` contains the Python, FastAPI, Docling, retrieval, and generation services.
- `frontend/` is reserved for the SvelteKit and shadcn-svelte application.
- `api_spec.md` defines the normative product behavior and frontend integration rules.
- `openapi.v1.yaml` defines the complete versioned HTTP shapes for type and mock generation.
- `plan.md` defines the phased implementation and production-readiness roadmap.

## Current status

Phase 0 foundation work is in progress. PostgreSQL/pgvector lifecycle, the initial content schema,
secure local artifact storage, the catalog repository/transaction boundary, and the
frontend-facing API v1 contract are implemented. Only the health probes are currently live;
catalog, ingestion, retrieval, and answer-generation APIs are not available yet.

## Development

Prerequisites:

- Python 3.13, managed by `uv`
- `uv`
- Docker with Compose

Start the pinned PostgreSQL 18/pgvector 0.8.2 development database from the repository root:

```shell
docker compose up -d --wait database
```

The database is exposed only on `127.0.0.1:55432` to avoid common local PostgreSQL conflicts. Its
named volume is mounted at PostgreSQL 18's `/var/lib/postgresql` persistence boundary. The committed
credentials are development-only defaults and must not be reused outside local development.

Run backend commands from `backend/`:

```shell
cd backend
uv sync --locked --all-groups
```

Create a local configuration file from the safe development template:

```shell
cp .env.example .env
```

All backend environment variables use the `TNPSC_` prefix. Provider keys are optional and the
committed templates contain no credentials. Tests construct isolated settings and do not load a
developer's `.env` file.

Apply package-owned migrations after the database is healthy:

```shell
uv run --locked alembic upgrade head
```

Migration `0001` enables pgvector; `0002` creates the initial content schema and a fixed
384-dimensional vector column without an approximate-nearest-neighbor index. `/health/live`
reports only that the API process is alive; `/health/ready` requires both PostgreSQL/pgvector and
the configured artifact root. Migration tests are opt-in because they rebuild a disposable
database and write a complete sample content graph:

```shell
TNPSC_TEST_DATABASE_URL=postgresql+psycopg://tnpsc:tnpsc@127.0.0.1:55432/tnpsc \
  uv run --locked pytest -m postgres
```

The API emits guarded structlog JSON events and OpenTelemetry server spans. Traces remain
in-process unless `TNPSC_OTEL_TRACES_ENDPOINT` points to an OTLP/HTTP collector. The logging
processor accepts only stable event names and an explicit metadata allowlist; unstructured messages
are redacted. Request bodies, query strings, textbook content, prompts, evidence, model output, and
exception messages are excluded by default.

The MVP artifact adapter stores immutable files below `TNPSC_ARTIFACT_ROOT`, which defaults to the
ignored `backend/artifacts/` directory when commands run from `backend/`. Keys are generated from
server-owned UUIDs, SHA-256 checksums, and detected media types rather than upload filenames. Writes
are streamed to same-directory temporary files and committed atomically; a repeated key is accepted
only when its bytes match. Production configuration requires an absolute artifact root. A shared
Docker volume will be mounted when the API and worker container services are added.

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
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked ty check
uv run --locked pyrefly check
uv run --locked pytest
```

Run the FastAPI development server:

```shell
uv run --locked fastapi dev src/tnpsc_book_rag/main.py
```

The initial liveness endpoint is available at `GET /health/live`.
