"""Real-PostgreSQL tests for atomic parent-child extraction persistence."""

import asyncio
import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tnpsc_book_rag.catalog.entities import Book, BookDocument
from tnpsc_book_rag.catalog.models import DocumentState
from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.db import (
    BookDocumentRecord,
    BookRecord,
    ChunkPageRecord,
    ChunkRecord,
    ContentUnitPageRecord,
    ContentUnitRecord,
    IngestionRunRecord,
    PageRecord,
    SqlAlchemyCatalogRepository,
    create_database,
)
from tnpsc_book_rag.db.repositories.catalog import (
    _legacy_parent_child_result,
    _validate_parent_child_graph,
)
from tnpsc_book_rag.ingestion.entities import IngestionRun, IngestionWorkItem
from tnpsc_book_rag.ingestion.models import IngestionStage
from tnpsc_book_rag.ingestion.status import IngestionRunStatus
from tnpsc_extraction.models import (
    ChunkContentType,
    ContentUnitType,
    DisplayFormat,
    ExtractedBlock,
    ExtractedChunk,
    ExtractedContentUnit,
    ExtractedPage,
    ExtractedRetrievalChunk,
    ExtractionBundle,
    TextbookChunkingResult,
)

_BACKEND_ROOT = Path(__file__).parents[2]


class ExpectedRollback(RuntimeError):
    """Sentinel proving that the repository never owns the commit boundary."""


def _test_database_url() -> str:
    value = os.environ.get("TNPSC_TEST_DATABASE_URL")
    if not value:
        pytest.skip("TNPSC_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _parent_sha256(display_text: str) -> str:
    value = {
        "display_format": "plain_text",
        "display_text": display_text,
        "structured_content": None,
    }
    return _text_sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )


async def _add_claimed_source(session: AsyncSession, suffix: str) -> IngestionWorkItem:
    now = datetime.now(UTC)
    book = BookRecord(
        title=f"Persistence fixture {suffix}",
        standard=6,
        subject="Science",
        publisher="Government of Tamil Nadu",
        catalog_identifier=f"parent-child-{suffix}",
    )
    session.add(book)
    await session.flush()
    document = BookDocumentRecord(
        book_id=book.id,
        edition="Term I",
        source_filename="science.pdf",
        source_artifact_key=f"sources/{suffix}.pdf",
        source_sha256=hashlib.sha256(suffix.encode()).hexdigest(),
        file_size_bytes=1024,
        state=DocumentState.EXTRACTING,
    )
    session.add(document)
    await session.flush()
    run = IngestionRunRecord(
        document_id=document.id,
        status=IngestionRunStatus.RUNNING,
        current_stage=IngestionStage.EXTRACTION,
        started_at=now,
        worker_id="test-worker",
    )
    session.add(run)
    await session.flush()
    return IngestionWorkItem(
        book=Book(
            id=book.id,
            title=book.title,
            standard=book.standard,
            subject=book.subject,
            language=book.language,
            publisher=book.publisher,
            catalog_identifier=book.catalog_identifier,
            created_at=now,
            updated_at=now,
        ),
        document=BookDocument(
            id=document.id,
            book_id=book.id,
            edition=document.edition,
            source_filename=document.source_filename,
            media_type=document.media_type,
            source_artifact_key=document.source_artifact_key,
            docling_artifact_key=None,
            source_sha256=document.source_sha256,
            file_size_bytes=document.file_size_bytes,
            page_count=None,
            state=DocumentState.EXTRACTING,
            activated_at=None,
            created_at=now,
            updated_at=now,
        ),
        ingestion_run=IngestionRun(
            id=run.id,
            document_id=document.id,
            status=IngestionRunStatus.RUNNING,
            current_stage=IngestionStage.EXTRACTION,
            retry_count=0,
            started_at=now,
            completed_at=None,
            warnings=(),
            error=None,
            created_at=now,
            updated_at=now,
        ),
    )


def _bundle(root: Path) -> ExtractionBundle:
    text_one = "Matter occupies space."
    text_two = "Matter has mass."
    return ExtractionBundle(
        pages=(
            ExtractedPage(
                pdf_page_index=0,
                width=200,
                height=300,
                raw_text=text_one,
                normalized_text=text_one,
                blocks=(ExtractedBlock(text_one, "prose", 0, None, None),),
                warnings=(),
            ),
            ExtractedPage(
                pdf_page_index=1,
                width=200,
                height=300,
                raw_text=text_two,
                normalized_text=text_two,
                blocks=(ExtractedBlock(text_two, "prose", 1, None, None),),
                warnings=(),
            ),
        ),
        assets=(),
        docling_json_path=root / "docling.json",
        page_count=2,
        docling_version="2.112.0",
        config_fingerprint="a" * 64,
    )


def _chunking() -> TextbookChunkingResult:
    parent_text = "Matter occupies space.\n\nMatter has mass."
    parent = ExtractedContentUnit(
        local_id="U000000",
        sequence_number=0,
        unit_type=ContentUnitType.DEFINITION,
        display_text=parent_text,
        display_format=DisplayFormat.PLAIN_TEXT,
        structured_content=None,
        section_path=("Matter",),
        retrieval_eligible=True,
        exclusion_reason=None,
        content_sha256=_parent_sha256(parent_text),
        page_indexes=(0, 1),
        docling_refs=("#/texts/0", "#/texts/1"),
        provenance={"fixture": True},
    )
    child_texts = ("Matter occupies space.", "Matter has mass.")
    children = tuple(
        ExtractedRetrievalChunk(
            local_id=f"C{sequence:06d}",
            parent_local_id=parent.local_id,
            sequence_number=sequence,
            display_text=value,
            display_format=DisplayFormat.PLAIN_TEXT,
            embedding_text=f"Matter | {value}",
            chapter_title="Matter",
            section_path=("Matter",),
            content_type=ChunkContentType.PROSE,
            token_count=5,
            display_sha256=_text_sha256(value),
            embedding_sha256=_text_sha256(f"Matter | {value}"),
            page_indexes=(sequence,),
            docling_refs=(f"#/texts/{sequence}",),
            provenance={"fixture": sequence},
        )
        for sequence, value in enumerate(child_texts)
    )
    return TextbookChunkingResult(
        content_units=(parent,),
        chunks=children,
        implementation_version="textbook-parent-child-v2",
        tokenizer_identifier="BAAI/bge-small-en-v1.5",
        tokenizer_revision="fixture-revision",
        config_fingerprint="b" * 64,
    )


def test_legacy_chunks_receive_exact_one_to_one_parent_checksums(tmp_path: Path) -> None:
    """The transitional CPU worker remains writable after the parent foreign key is required."""
    display_text = "Matter occupies space."
    embedding_text = "Science | Matter occupies space."
    result = _legacy_parent_child_result(
        (
            ExtractedChunk(
                page_index=0,
                sequence_number=0,
                display_text=display_text,
                embedding_text=embedding_text,
                chapter_title="Matter",
                section_path=("Matter",),
                content_type=ChunkContentType.PROSE,
                token_count=5,
                content_sha256=_text_sha256(display_text),
                provenance={},
            ),
        )
    )

    assert result.content_units[0].local_id == "U000000"
    assert result.content_units[0].unit_type is ContentUnitType.MIXED
    assert result.chunks[0].parent_local_id == "U000000"
    assert result.chunks[0].embedding_sha256 == _text_sha256(embedding_text)
    _validate_parent_child_graph(
        replace(_bundle(tmp_path), pages=_bundle(tmp_path).pages[:1], page_count=1),
        result,
        (),
    )


def test_parent_child_validation_rejects_changed_embedding_text(tmp_path: Path) -> None:
    """Persistence cannot accept a child checksum from different embedding content."""
    chunking = _chunking()
    changed_child = replace(chunking.chunks[0], embedding_text="changed after chunking")
    changed = replace(chunking, chunks=(changed_child, *chunking.chunks[1:]))

    with pytest.raises(ValueError, match="embedding checksum"):
        _validate_parent_child_graph(_bundle(tmp_path), changed, ())


def test_parent_child_validation_rejects_a_parent_without_children(tmp_path: Path) -> None:
    """Every stored semantic parent must remain reachable from retrieval results."""
    chunking = _chunking()
    orphan_text = "Matter can exist as a solid, liquid, or gas."
    orphan = replace(
        chunking.content_units[0],
        local_id="U000001",
        sequence_number=1,
        display_text=orphan_text,
        content_sha256=_parent_sha256(orphan_text),
    )
    changed = replace(chunking, content_units=(*chunking.content_units, orphan))

    with pytest.raises(ValueError, match="at least one retrieval child"):
        _validate_parent_child_graph(_bundle(tmp_path), changed, ())


async def _exercise_parent_child_persistence(settings: Settings, tmp_path: Path) -> None:
    database = create_database(settings)
    assert database is not None
    success_book_id: UUID | None = None
    rollback_book_id: UUID | None = None
    try:
        async with database.transaction() as session:
            success_work = await _add_claimed_source(session, uuid4().hex)
            success_book_id = success_work.document.book_id
        async with database.transaction() as session:
            await SqlAlchemyCatalogRepository(session).persist_parent_child_extraction(
                success_work,
                _bundle(tmp_path),
                _chunking(),
                (),
            )

        async with database.transaction() as session:
            parent_count = await session.scalar(
                select(func.count())
                .select_from(ContentUnitRecord)
                .where(ContentUnitRecord.document_id == success_work.document.id)
            )
            parent_page_count = await session.scalar(
                select(func.count())
                .select_from(ContentUnitPageRecord)
                .join(ContentUnitRecord)
                .where(ContentUnitRecord.document_id == success_work.document.id)
            )
            chunks = tuple(
                (
                    await session.scalars(
                        select(ChunkRecord)
                        .where(ChunkRecord.document_id == success_work.document.id)
                        .order_by(ChunkRecord.sequence_number)
                    )
                ).all()
            )
            chunk_page_count = await session.scalar(
                select(func.count())
                .select_from(ChunkPageRecord)
                .join(ChunkRecord)
                .where(ChunkRecord.document_id == success_work.document.id)
            )
            run = await session.get(IngestionRunRecord, success_work.ingestion_run.id)
            assert parent_count == 1
            assert parent_page_count == 2
            assert len(chunks) == 2
            assert chunk_page_count == 2
            assert chunks[0].content_unit_id == chunks[1].content_unit_id
            assert chunks[0].embedding_sha256 == _chunking().chunks[0].embedding_sha256
            assert run is not None
            assert run.chunker_version == "textbook-parent-child-v2"
            assert run.chunker_config_fingerprint == "b" * 64
            assert run.chunker_tokenizer_identifier == "BAAI/bge-small-en-v1.5"
            assert run.chunker_tokenizer_revision == "fixture-revision"
            assert run.status is IngestionRunStatus.SUCCEEDED

        async with database.transaction() as session:
            rollback_work = await _add_claimed_source(session, uuid4().hex)
            rollback_book_id = rollback_work.document.book_id
        with pytest.raises(ExpectedRollback):
            async with database.transaction() as session:
                await SqlAlchemyCatalogRepository(session).persist_parent_child_extraction(
                    rollback_work,
                    _bundle(tmp_path),
                    _chunking(),
                    (),
                )
                raise ExpectedRollback
        async with database.transaction() as session:
            rolled_back_pages = await session.scalar(
                select(func.count())
                .select_from(PageRecord)
                .where(PageRecord.document_id == rollback_work.document.id)
            )
            rolled_back_parents = await session.scalar(
                select(func.count())
                .select_from(ContentUnitRecord)
                .where(ContentUnitRecord.document_id == rollback_work.document.id)
            )
            rolled_back_chunks = await session.scalar(
                select(func.count())
                .select_from(ChunkRecord)
                .where(ChunkRecord.document_id == rollback_work.document.id)
            )
            run = await session.get(IngestionRunRecord, rollback_work.ingestion_run.id)
            assert (rolled_back_pages, rolled_back_parents, rolled_back_chunks) == (0, 0, 0)
            assert run is not None
            assert run.status is IngestionRunStatus.RUNNING
            assert run.chunker_config_fingerprint is None
    finally:
        for book_id in (success_book_id, rollback_book_id):
            if book_id is not None:
                async with database.transaction() as session:
                    await session.execute(delete(BookRecord).where(BookRecord.id == book_id))
        await database.close()


@pytest.mark.postgres
def test_parent_child_persistence_is_complete_and_caller_transactional(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Parents, children, joins, and run metadata commit or roll back as one graph."""
    database_url = _test_database_url()
    monkeypatch.setenv("TNPSC_DATABASE_URL", database_url)
    command.upgrade(Config(str(_BACKEND_ROOT / "alembic.ini")), "head")
    settings = Settings.model_validate({"database_url": database_url})

    asyncio.run(_exercise_parent_child_persistence(settings, tmp_path))
