"""Tests for routing claimed work through an offline package when available."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest

from tnpsc_book_rag.catalog.entities import Book, BookDocument
from tnpsc_book_rag.catalog.models import DocumentLanguage, DocumentState
from tnpsc_book_rag.extraction import DoclingExtractor
from tnpsc_book_rag.ingestion.entities import IngestionRun, IngestionWorkItem
from tnpsc_book_rag.ingestion.models import IngestionStage
from tnpsc_book_rag.ingestion.ports import IngestionRepository
from tnpsc_book_rag.ingestion.service import (
    ClaimedPackageImporter,
    ExtractionPackageLocator,
    IngestionService,
    IngestionTransactionFactory,
)
from tnpsc_book_rag.ingestion.status import IngestionRunStatus
from tnpsc_book_rag.storage import ArtifactStorage


def _work_item() -> IngestionWorkItem:
    now = datetime.now(UTC)
    book_id = uuid4()
    document_id = uuid4()
    book = Book(
        id=book_id,
        title="Standard 6 Science",
        standard=6,
        subject="Science",
        language=DocumentLanguage.ENGLISH,
        publisher="Government of Tamil Nadu",
        catalog_identifier=None,
        created_at=now,
        updated_at=now,
    )
    document = BookDocument(
        id=document_id,
        book_id=book_id,
        edition="Term I",
        source_filename="science.pdf",
        media_type="application/pdf",
        source_artifact_key=f"sources/{'a' * 64}.pdf",
        docling_artifact_key=None,
        source_sha256="a" * 64,
        file_size_bytes=100,
        page_count=None,
        state=DocumentState.EXTRACTING,
        activated_at=None,
        created_at=now,
        updated_at=now,
    )
    run = IngestionRun(
        id=uuid4(),
        document_id=document_id,
        status=IngestionRunStatus.RUNNING,
        current_stage=IngestionStage.EXTRACTION,
        retry_count=0,
        started_at=now,
        completed_at=None,
        warnings=(),
        error=None,
        created_at=now,
        updated_at=now,
    )
    return IngestionWorkItem(book, document, run)


class _Repository:
    def __init__(self, work_item: IngestionWorkItem) -> None:
        self.work_item: IngestionWorkItem | None = work_item
        self.failure: tuple[str, str] | None = None

    async def claim_next_ingestion_run(self, worker_id: str) -> IngestionWorkItem | None:
        claimed = self.work_item
        self.work_item = None
        return claimed

    async def mark_ingestion_failed(
        self,
        run_id: UUID,
        *,
        code: str,
        message: str,
        completed_at: datetime,
    ) -> None:
        self.failure = (code, message)


class _Locator:
    def __init__(self, archive: Path) -> None:
        self.archive = archive
        self.checksums: list[str] = []

    async def find_by_source_sha256(self, source_sha256: str) -> Path | None:
        self.checksums.append(source_sha256)
        return self.archive


class _Importer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.imported: tuple[IngestionWorkItem, Path] | None = None

    async def import_claimed_package(
        self,
        work_item: IngestionWorkItem,
        archive_path: Path,
    ) -> None:
        if self.fail:
            raise ValueError("private package failure")
        self.imported = (work_item, archive_path)


def _service(
    repository: _Repository,
    locator: _Locator,
    importer: _Importer,
) -> IngestionService:
    @asynccontextmanager
    async def transaction() -> AsyncGenerator[IngestionRepository]:
        yield cast(IngestionRepository, repository)

    return IngestionService(
        cast(IngestionTransactionFactory, transaction),
        cast(ArtifactStorage, object()),
        extractor=cast(DoclingExtractor, object()),
        package_locator=cast(ExtractionPackageLocator, locator),
        package_importer=cast(ClaimedPackageImporter, importer),
    )


@pytest.mark.anyio
async def test_worker_prefers_matching_offline_package(tmp_path: Path) -> None:
    work_item = _work_item()
    repository = _Repository(work_item)
    locator = _Locator(tmp_path / "science.zip")
    importer = _Importer()

    assert await _service(repository, locator, importer).run_once("demo-worker")

    assert locator.checksums == [work_item.document.source_sha256]
    assert importer.imported == (work_item, locator.archive)
    assert repository.failure is None


@pytest.mark.anyio
async def test_package_failure_is_sanitized_and_marks_claimed_run_failed(tmp_path: Path) -> None:
    work_item = _work_item()
    repository = _Repository(work_item)
    service = _service(repository, _Locator(tmp_path / "broken.zip"), _Importer(fail=True))

    assert await service.run_once("demo-worker")

    assert repository.failure is not None
    assert repository.failure[0] == "extraction_failed"
    assert "private package failure" not in repository.failure[1]


def test_package_locator_and_importer_must_be_configured_together() -> None:
    @asynccontextmanager
    async def transaction() -> AsyncGenerator[IngestionRepository]:
        yield cast(IngestionRepository, object())

    with pytest.raises(ValueError, match="configured together"):
        IngestionService(
            cast(IngestionTransactionFactory, transaction),
            cast(ArtifactStorage, object()),
            extractor=cast(DoclingExtractor, object()),
            package_locator=cast(ExtractionPackageLocator, _Locator(Path("science.zip"))),
        )
