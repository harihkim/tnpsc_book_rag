# TNPSC Book RAG backend

FastAPI backend for textbook ingestion, retrieval, and grounded answer generation.

See the repository-level `README.md` and `plan.md` for the full project roadmap.

Alembic configuration lives in `alembic.ini`; migration assets are packaged under
`tnpsc_book_rag.db.migrations` so the application and deployment artifact use the same revisions.
The registered SQLAlchemy records live under `tnpsc_book_rag.db.models`. PDF page indexes are
zero-based in storage, activation uses a nullable timestamp with one active document per book, and
embeddings are versioned separately from immutable chunk content.
