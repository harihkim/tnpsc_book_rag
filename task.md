# Execution Tasks: Deployment & Backend Refactoring

- [/] Phase 1: Descriptive Backend Folder Renaming
  - [ ] Rename subdirectories in `backend/src/tnpsc_book_rag/` (`adapters` -> `rag_adapters`, `api` -> `http_api`, `catalog` -> `textbook_catalog`, `db` -> `database_persistence`, `extraction` -> `pdf_extraction`, `ingestion` -> `ingestion_pipeline`, `inspection` -> `debug_inspection`, `observability` -> `telemetry_logging`, `storage` -> `artifact_storage`)
  - [ ] Update imports across `backend/src`, `backend/scripts`, `backend/main.py`, `backend/worker.py`, and `backend/tests`
  - [ ] Run backend `pytest` to verify refactoring

- [ ] Phase 2: S3 / Backblaze B2 Storage Adapter
  - [ ] Add `boto3` dependency to `backend/pyproject.toml`
  - [ ] Add S3 configuration fields & environment safety validation to `config.py`
  - [ ] Implement `S3ArtifactStorage` in `artifact_storage/s3.py`
  - [ ] Update `create_artifact_storage()` factory in `artifact_storage/__init__.py`
  - [ ] Add and run unit tests in `tests/artifact_storage/test_s3.py`

- [ ] Phase 3: Local Data Export & Migration Scripts
  - [ ] Export local PostgreSQL database (with vector embeddings) to `local_tnpsc_data.sql`
  - [ ] Create `backend/scripts/migrate_local_artifacts_to_b2.py` script to push local `backend/artifacts/` files up to B2

- [ ] Phase 4: Cloud Deployment Configuration & Final Verification
  - [ ] Create `heroku.yml` and adjust `backend/Dockerfile` for Heroku Web API container deployment
  - [ ] Create SPA fallback `_redirects` file for Cloudflare Pages in `frontend/static/`
  - [ ] Verify frontend with `pnpm run check` and backend with `pytest`
