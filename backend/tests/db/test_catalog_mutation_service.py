"""Real-PostgreSQL integration for idempotent catalog mutation and upload acceptance."""

import asyncio
import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select

from tnpsc_book_rag.catalog.entities import NewBook
from tnpsc_book_rag.catalog.models import DocumentState
from tnpsc_book_rag.catalog.mutations import (
    DuplicateSourceError,
    IdempotencyConflictError,
    PendingDocumentUpload,
)
from tnpsc_book_rag.catalog.services import CatalogService
from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.db import (
    BookDocumentRecord,
    BookRecord,
    IdempotencyRecord,
    IngestionRunRecord,
    create_database,
)
from tnpsc_book_rag.db.repositories import catalog_transaction
from tnpsc_book_rag.ingestion.status import IngestionRunStatus
from tnpsc_book_rag.storage import LocalArtifactStorage

_BACKEND_ROOT = Path(__file__).parents[2]


def _test_database_url() -> str:
    value = os.environ.get("TNPSC_TEST_DATABASE_URL")
    if not value:
        pytest.skip("TNPSC_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


async def _exercise_mutation_service(settings: Settings, artifact_root: Path) -> None:
    database = create_database(settings)
    assert database is not None
    suffix = uuid4().hex
    create_key = f"create-{suffix}"
    upload_key = f"upload-{suffix}"
    duplicate_key = f"duplicate-{suffix}"
    book_id = None
    service = CatalogService(
        lambda: catalog_transaction(database),
        storage=LocalArtifactStorage(artifact_root),
        max_upload_bytes=1_024,
    )
    new_book = NewBook(
        title=f"Mutation integration {suffix}",
        standard=8,
        subject="Science",
        publisher="Tamil Nadu Textbook Corporation",
        catalog_identifier=f"mutation-{suffix}",
    )
    pdf = b"%PDF-1.7\nphase-zero-integration"

    try:
        created = await service.create_book(new_book, idempotency_key=create_key)
        book_id = created.value.id
        replayed_book = await service.create_book(new_book, idempotency_key=create_key)
        assert replayed_book.replayed is True
        assert replayed_book.value == created.value
        assert replayed_book.headers == created.headers

        with pytest.raises(IdempotencyConflictError):
            await service.create_book(
                NewBook(
                    title=f"Changed mutation {suffix}",
                    standard=8,
                    subject="History",
                    publisher="Tamil Nadu Textbook Corporation",
                ),
                idempotency_key=create_key,
            )

        accepted = await service.upload_document(
            book_id,
            PendingDocumentUpload(
                filename="science.pdf",
                media_type="application/pdf",
                edition="2025-2026",
                source=BytesIO(pdf),
            ),
            idempotency_key=upload_key,
        )
        replayed_upload = await service.upload_document(
            book_id,
            PendingDocumentUpload(
                filename="science.pdf",
                media_type="application/pdf",
                edition="2025-2026",
                source=BytesIO(pdf),
            ),
            idempotency_key=upload_key,
        )
        assert replayed_upload.replayed is True
        assert replayed_upload.value == accepted.value

        with pytest.raises(DuplicateSourceError):
            await service.upload_document(
                book_id,
                PendingDocumentUpload(
                    filename="duplicate.pdf",
                    media_type="application/pdf",
                    edition="2026-2027",
                    source=BytesIO(pdf),
                ),
                idempotency_key=duplicate_key,
            )

        async with database.transaction() as session:
            document_count = await session.scalar(
                select(func.count())
                .select_from(BookDocumentRecord)
                .where(BookDocumentRecord.book_id == book_id)
            )
            run_count = await session.scalar(
                select(func.count())
                .select_from(IngestionRunRecord)
                .where(IngestionRunRecord.document_id == accepted.value.document.id)
            )
            snapshot_count = await session.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.key.in_((create_key, upload_key)))
            )
            document = await session.get(BookDocumentRecord, accepted.value.document.id)
            run = await session.get(IngestionRunRecord, accepted.value.ingestion_run.id)
            assert document_count == 1
            assert run_count == 1
            assert snapshot_count == 2
            assert document is not None and document.state is DocumentState.QUEUED
            assert run is not None and run.status is IngestionRunStatus.QUEUED
    finally:
        async with database.transaction() as session:
            await session.execute(
                delete(IdempotencyRecord).where(
                    IdempotencyRecord.key.in_((create_key, upload_key, duplicate_key))
                )
            )
            if book_id is not None:
                await session.execute(delete(BookRecord).where(BookRecord.id == book_id))
        await database.close()


@pytest.mark.postgres
def test_catalog_mutation_service_is_transactional_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Creation, upload, queueing, and replay survive real transaction boundaries."""
    database_url = _test_database_url()
    monkeypatch.setenv("TNPSC_DATABASE_URL", database_url)
    command.upgrade(Config(str(_BACKEND_ROOT / "alembic.ini")), "head")
    settings = Settings.model_validate({"database_url": database_url})

    asyncio.run(_exercise_mutation_service(settings, tmp_path))
