"""Real-PostgreSQL tests for catalog repositories and transaction ownership."""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete

from tnpsc_book_rag.catalog import NewBook, NewBookDocument
from tnpsc_book_rag.catalog.models import CatalogStatus, DocumentState
from tnpsc_book_rag.catalog.read_models import BookListFilters
from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.db import (
    BookDocumentRecord,
    BookRecord,
    SqlAlchemyCatalogRepository,
    create_database,
)

_BACKEND_ROOT = Path(__file__).parents[2]


class ExpectedRollback(RuntimeError):
    """Sentinel exception used to exercise transaction rollback."""


def _test_database_url() -> str:
    value = os.environ.get("TNPSC_TEST_DATABASE_URL")
    if not value:
        pytest.skip("TNPSC_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


async def _exercise_catalog_repository(settings: Settings) -> None:
    database = create_database(settings)
    assert database is not None
    committed_book_id: UUID | None = None
    rollback_book_id: UUID | None = None
    suffix = uuid4().hex

    try:
        with pytest.raises(ExpectedRollback):
            async with database.transaction() as session:
                repository = SqlAlchemyCatalogRepository(session)
                rolled_back = await repository.add_book(
                    NewBook(
                        title="Rollback fixture",
                        standard=6,
                        subject="Science",
                        publisher="Tamil Nadu Textbook Corporation",
                        catalog_identifier=f"rollback-{suffix}",
                    )
                )
                rollback_book_id = rolled_back.id
                raise ExpectedRollback

        assert rollback_book_id is not None
        async with database.transaction() as session:
            repository = SqlAlchemyCatalogRepository(session)
            assert await repository.get_book(rollback_book_id) is None

            book = await repository.add_book(
                NewBook(
                    title=f"Repository fixture {suffix}",
                    standard=8,
                    subject="Science",
                    publisher="Tamil Nadu Textbook Corporation",
                    catalog_identifier=f"repository-{suffix}",
                )
            )
            committed_book_id = book.id
            document = await repository.add_document(
                NewBookDocument(
                    book_id=book.id,
                    edition="2025-2026",
                    source_filename="science-standard-8.pdf",
                    source_artifact_key=f"sources/{book.id}/source.pdf",
                    source_sha256=uuid4().hex * 2,
                    file_size_bytes=4096,
                )
            )

            assert document.book_id == book.id
            assert document.state.value == "uploaded"
            assert await repository.get_document(document.id) == document
            assert await repository.get_document_by_checksum(document.source_sha256) == document
            assert await repository.list_documents(book.id) == (document,)
            initial_catalog = await repository.get_catalog_book(book.id)
            assert initial_catalog is not None
            assert initial_catalog.book.catalog_status is CatalogStatus.PROCESSING
            assert initial_catalog.book.latest_document_state is DocumentState.UPLOADED

            document_record = await session.get(BookDocumentRecord, document.id)
            assert document_record is not None
            document_record.state = DocumentState.READY
            document_record.page_count = 212
            document_record.activated_at = datetime.now(UTC)
            await session.flush()

            ready_catalog = await repository.get_catalog_book(book.id)
            assert ready_catalog is not None
            assert ready_catalog.book.catalog_status is CatalogStatus.READY
            assert ready_catalog.book.active_document_id == document.id
            assert ready_catalog.documents[0].id == document.id

            filters = BookListFilters(
                standards=(8,),
                subjects=("sCiEnCe",),
                query=suffix,
            )
            window = await repository.list_catalog_books(filters, limit=20)
            assert [item.id for item in window.items] == [book.id]
            assert await repository.count_catalog_books(filters) == 1
            options = await repository.list_ready_book_options()
            assert book.id in {option.id for option in options}

        async with database.transaction() as session:
            repository = SqlAlchemyCatalogRepository(session)
            persisted_book = await repository.get_book(committed_book_id)
            persisted_documents = await repository.list_documents(committed_book_id)

            assert persisted_book is not None
            assert persisted_book.title == f"Repository fixture {suffix}"
            assert len(persisted_documents) == 1
            assert persisted_documents[0].source_filename == "science-standard-8.pdf"
    finally:
        if committed_book_id is not None:
            async with database.transaction() as session:
                await session.execute(delete(BookRecord).where(BookRecord.id == committed_book_id))
        await database.close()


@pytest.mark.postgres
def test_catalog_repository_obeys_database_transaction_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal context exit commits and exceptional exit rolls back the complete unit of work."""
    database_url = _test_database_url()
    monkeypatch.setenv("TNPSC_DATABASE_URL", database_url)
    command.upgrade(Config(str(_BACKEND_ROOT / "alembic.ini")), "head")
    settings = Settings.model_validate({"database_url": database_url})

    asyncio.run(_exercise_catalog_repository(settings))
