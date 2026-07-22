"""Real-PostgreSQL tests for controlled ingestion and extraction inspection."""

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete

from tnpsc_book_rag.textbook_catalog.models import (
    AssetType,
    ChunkContentType,
    DocumentState,
)
from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.database_persistence import (
    AssetRecord,
    BookDocumentRecord,
    BookRecord,
    ChunkPageRecord,
    ChunkRecord,
    ContentUnitRecord,
    IngestionRunRecord,
    PageRecord,
    create_database,
)
from tnpsc_book_rag.database_persistence.repositories.inspection import SqlAlchemyInspectionRepository
from tnpsc_book_rag.ingestion_pipeline.models import IngestionStage
from tnpsc_book_rag.ingestion_pipeline.status import IngestionRunStatus
from tnpsc_book_rag.debug_inspection.models import RunListFilters
from tnpsc_extraction.models import ContentUnitType, DisplayFormat

_BACKEND_ROOT = Path(__file__).parents[2]


def _test_database_url() -> str:
    value = os.environ.get("TNPSC_TEST_DATABASE_URL")
    if not value:
        pytest.skip("TNPSC_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _parent_sha256(value: str) -> str:
    payload = json.dumps(
        {
            "display_format": "plain_text",
            "display_text": value,
            "structured_content": None,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return _text_sha256(payload)


async def _exercise_inspection_repository(settings: Settings) -> None:
    database = create_database(settings)
    assert database is not None
    book_id: UUID | None = None
    try:
        now = datetime.now(UTC)
        async with database.transaction() as session:
            book = BookRecord(
                title="Inspection fixture",
                standard=6,
                subject="Science",
                publisher="Government of Tamil Nadu",
                catalog_identifier=f"inspection-{uuid4().hex}",
            )
            session.add(book)
            await session.flush()
            book_id = book.id
            document = BookDocumentRecord(
                book_id=book.id,
                edition="Term I",
                source_filename="science.pdf",
                source_artifact_key=f"sources/{uuid4().hex}.pdf",
                source_sha256=uuid4().hex * 2,
                file_size_bytes=4096,
                page_count=2,
                state=DocumentState.CHUNKING,
            )
            session.add(document)
            await session.flush()
            run = IngestionRunRecord(
                document_id=document.id,
                status=IngestionRunStatus.SUCCEEDED,
                current_stage=IngestionStage.CHUNKING,
                worker_id="inspection-test",
                started_at=now,
                completed_at=now,
                warning_details=[{"code": "empty_text_layer", "message": "page has no text"}],
            )
            session.add(run)
            await session.flush()
            pages = [
                PageRecord(
                    document_id=document.id,
                    ingestion_run_id=run.id,
                    pdf_page_index=index,
                    width=612,
                    height=792,
                    raw_text=f"Raw page {index}",
                    normalized_text=f"Page {index}",
                    extraction_warnings=(
                        [{"code": "empty_text_layer", "message": "page has no text"}]
                        if index == 0
                        else []
                    ),
                )
                for index in range(2)
            ]
            session.add_all(pages)
            await session.flush()
            parent_text = "Matter occupies space."
            parent = ContentUnitRecord(
                document_id=document.id,
                ingestion_run_id=run.id,
                source_local_id="U000000",
                sequence_number=0,
                unit_type=ContentUnitType.DEFINITION,
                display_text=parent_text,
                display_format=DisplayFormat.PLAIN_TEXT,
                structured_content=None,
                section_path=["Matter"],
                retrieval_eligible=True,
                exclusion_reason=None,
                content_sha256=_parent_sha256(parent_text),
                docling_refs=["#/texts/0"],
                provenance={"fixture": True},
            )
            session.add(parent)
            await session.flush()
            chunks: list[ChunkRecord] = []
            for index, page in enumerate(pages):
                display_text = f"Matter fact {index}."
                embedding_text = f"Matter\n{display_text}"
                chunk = ChunkRecord(
                    content_unit_id=parent.id,
                    page_id=page.id,
                    document_id=document.id,
                    ingestion_run_id=run.id,
                    source_local_id=f"C{index:06d}",
                    sequence_number=index,
                    display_text=display_text,
                    display_format=DisplayFormat.PLAIN_TEXT,
                    embedding_text=embedding_text,
                    chapter_title="Matter",
                    section_path=["Matter"],
                    content_type=ChunkContentType.PROSE,
                    token_count=5,
                    display_sha256=_text_sha256(display_text),
                    embedding_sha256=_text_sha256(embedding_text),
                    docling_refs=[f"#/texts/{index}"],
                    provenance={"fixture": index},
                )
                session.add(chunk)
                chunks.append(chunk)
            await session.flush()
            session.add_all(
                ChunkPageRecord(chunk_id=chunk.id, page_id=page.id, span_order=0)
                for chunk, page in zip(chunks, pages, strict=True)
            )
            session.add(
                AssetRecord(
                    page_id=pages[0].id,
                    ingestion_run_id=run.id,
                    asset_type=AssetType.DIAGRAM,
                    artifact_key=f"assets/{uuid4().hex}.png",
                    mime_type="image/png",
                    sha256="b" * 64,
                    width=800,
                    height=600,
                    thumbnail_artifact_key=f"thumbnails/{uuid4().hex}.png",
                    thumbnail_width=320,
                    thumbnail_height=240,
                    accessibility_status="caption_derived",
                    alt_text="Matter diagram",
                    alt_text_source="docling_caption",
                    caption="Matter diagram",
                    bounding_box={
                        "l": 10,
                        "b": 20,
                        "r": 100,
                        "t": 120,
                        "coord_origin": "BOTTOMLEFT",
                    },
                    coordinate_origin="BOTTOMLEFT",
                    source_reference="#/pictures/0",
                    provenance={"fixture": True},
                )
            )
            await session.flush()
            document_id = document.id
            run_id = run.id
            page_ids = tuple(page.id for page in pages)

        async with database.transaction() as session:
            repository = SqlAlchemyInspectionRepository(session)
            detail = await repository.get_document(document_id)
            assert detail is not None
            assert detail.latest_ingestion_run is not None
            assert detail.latest_ingestion_run.id == run_id
            assert detail.latest_ingestion_run.warnings[0] == {
                "code": "empty_text_layer",
                "message": "page has no text",
                "stage": "extraction",
                "pdf_page_index": None,
            }

            filters = RunListFilters(
                statuses=(IngestionRunStatus.SUCCEEDED,),
                stages=(IngestionStage.CHUNKING,),
                book_id=book_id,
                document_id=document_id,
            )
            operations = await repository.list_ingestion_operations(
                filters,
                limit=20,
                after=None,
                before=None,
            )
            assert [item.ingestion_run.id for item in operations.items] == [run_id]
            assert operations.items[0].book.title == "Inspection fixture"
            assert await repository.count_ingestion_operations(filters) == 1

            first_page = await repository.list_pages(
                document_id,
                limit=1,
                after=None,
                before=None,
            )
            assert first_page.has_next
            second_page = await repository.list_pages(
                document_id,
                limit=1,
                after=first_page.items[0].order_key,
                before=None,
            )
            assert second_page.items[0].pdf_page_index == 1
            assert second_page.has_previous
            assert await repository.count_pages(document_id) == 2

            page_detail = await repository.get_page(page_ids[0])
            assert page_detail is not None
            assert page_detail.warnings[0].pdf_page_index == 0
            assert [chunk.sequence_number for chunk in page_detail.chunks] == [0]
            assert page_detail.assets[0].alt_text_source == "caption"
            assert page_detail.assets[0].bounding_box is not None
            assert page_detail.assets[0].bounding_box.coordinate_origin == "bottom_left"

            updated = await repository.update_printed_page_label(page_ids[0], "iv")
            assert updated is not None
            assert updated.summary.printed_page_label == "iv"
            assert await repository.page_belongs_to_document(page_ids[0], document_id)
            assert not await repository.page_belongs_to_document(uuid4(), document_id)

            page_chunks = await repository.list_chunks(
                document_id,
                page_id=page_ids[0],
                limit=20,
                after=None,
                before=None,
            )
            assert [chunk.sequence_number for chunk in page_chunks.items] == [0]
            assert await repository.count_chunks(document_id, page_id=page_ids[0]) == 1
            assert await repository.count_chunks(document_id, page_id=None) == 2
    finally:
        if book_id is not None:
            async with database.transaction() as session:
                await session.execute(delete(BookRecord).where(BookRecord.id == book_id))
        await database.close()


@pytest.mark.postgres
def test_inspection_repository_reads_keysets_and_updates_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _test_database_url()
    monkeypatch.setenv("TNPSC_DATABASE_URL", database_url)
    command.upgrade(Config(str(_BACKEND_ROOT / "alembic.ini")), "head")
    settings = Settings.model_validate({"database_url": database_url})

    asyncio.run(_exercise_inspection_repository(settings))
