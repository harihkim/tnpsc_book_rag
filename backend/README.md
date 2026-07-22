# TNPSC Book RAG backend

FastAPI backend for textbook ingestion, retrieval, and grounded answer generation.

See the repository-level `README.md` and `plan.md` for the full project roadmap. The normative
frontend-facing behavior and route implementation status live in
[`api_spec.md`](../api_spec.md). The complete machine-readable contract used for frontend types,
mocks, and backend conformance is [`openapi.v1.yaml`](../openapi.v1.yaml).

Alembic configuration lives in `alembic.ini`; migration assets are packaged under
`tnpsc_book_rag.database_persistence.migrations` so the application and deployment artifact use the same revisions.
The registered SQLAlchemy records live under `tnpsc_book_rag.database_persistence.models`. PDF page indexes are
zero-based in storage, activation uses a nullable timestamp with one active document per book, and
embeddings are versioned separately from immutable chunk content.

`tnpsc_book_rag.textbook_catalog` owns immutable catalog entities and the repository protocol.
`SqlAlchemyCatalogRepository` adapts that protocol to one caller-owned async session, while
`Database.transaction()` owns commit, rollback, and session closure. Repository methods flush but
never commit. Book creation and upload acceptance use PostgreSQL advisory transaction locks plus
durable response snapshots, so a repeated idempotency key replays the original public response and
cannot create duplicate catalog or ingestion records.

`tnpsc_book_rag.artifact_storage` owns portable artifact keys, the provider-neutral storage protocol, and
the local filesystem adapter. The adapter performs blocking I/O through the context-preserving
thread boundary, rejects traversal and symlinks, verifies SHA-256 while streaming, and never
overwrites different bytes at an existing key. Accepted PDFs are bounded, signature-checked,
content-addressed, and persisted before the queued document and ingestion run commit atomically.

`tnpsc_book_rag.worker` validates PostgreSQL/pgvector and artifact storage, writes an atomic
heartbeat for container health checks, and processes queued Docling extraction jobs with the
CPU-only runtime. GPU extraction is performed offline with `scripts/extract_book.py`; the worker
does not require a GPU. When `TNPSC_EXTRACTION_PACKAGE_INBOX` is configured, the worker first
matches a queued PDF by SHA-256 against the unique verified package in that read-only directory.
A match is imported through the claimed ingestion run; otherwise the worker falls back to CPU
extraction. Keep only one chunking variant per source PDF in an inbox.

The repository-level `compose.yaml` starts the database, one-shot migrations, API, and worker with
health checks and a shared artifact volume. The CI workflow verifies the lockfile, runs Ruff, `ty`,
Pyrefly, offline tests, PostgreSQL migrations/integration tests, and validates the Compose topology.
