# TNPSC Book RAG backend

FastAPI backend for textbook ingestion, retrieval, and grounded answer generation.

See the repository-level `README.md` and `plan.md` for the full project roadmap.

Alembic configuration lives in `alembic.ini`; migration assets are packaged under
`tnpsc_book_rag.db.migrations` so the application and deployment artifact use the same revisions.
