"""CPU extraction path uses the shared TextbookChunker parent/child graph."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from docling_core.types.doc import (
    BoundingBox,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
    TableCell,
    TableData,
)

from tnpsc_book_rag.catalog.entities import Book, BookDocument
from tnpsc_book_rag.catalog.models import DocumentLanguage, DocumentState
from tnpsc_book_rag.extraction import DoclingExtractor, ExtractionBundle
from tnpsc_book_rag.extraction.chunking import TextbookChunker, TextbookChunkingConfig
from tnpsc_book_rag.extraction.persistence import StoredAsset
from tnpsc_book_rag.ingestion.entities import IngestionRun, IngestionWorkItem
from tnpsc_book_rag.ingestion.models import IngestionStage
from tnpsc_book_rag.ingestion.ports import IngestionRepository
from tnpsc_book_rag.ingestion.service import IngestionService, IngestionTransactionFactory
from tnpsc_book_rag.ingestion.status import IngestionRunStatus
from tnpsc_book_rag.storage import ArtifactStorage
from tnpsc_book_rag.storage.models import ArtifactKey
from tnpsc_extraction.models import TextbookChunkingResult


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
        source_artifact_key=f"sources/{'b' * 64}.pdf",
        docling_artifact_key=None,
        source_sha256="b" * 64,
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
        self.persisted: tuple[
            IngestionWorkItem,
            ExtractionBundle,
            TextbookChunkingResult,
            tuple[StoredAsset, ...],
        ] | None = None
        self.legacy_persist_called = False

    async def claim_next_ingestion_run(self, worker_id: str) -> IngestionWorkItem | None:
        claimed = self.work_item
        self.work_item = None
        return claimed

    async def persist_extraction(self, *args: object, **kwargs: object) -> None:
        self.legacy_persist_called = True
        raise AssertionError("CPU path must persist native parent/child graphs")

    async def persist_parent_child_extraction(
        self,
        work_item: IngestionWorkItem,
        bundle: ExtractionBundle,
        chunking: TextbookChunkingResult,
        assets: list[StoredAsset] | tuple[StoredAsset, ...],
        *,
        embedding_batch: object | None = None,
        embedding_generator: object | None = None,
    ) -> None:
        self.persisted = (work_item, bundle, chunking, tuple(assets))

    async def mark_ingestion_failed(
        self,
        run_id: UUID,
        *,
        code: str,
        message: str,
        completed_at: datetime,
    ) -> None:
        raise AssertionError(f"unexpected failure for {run_id}: {code} {message}")


class _Storage:
    def __init__(self, source_pdf: Path) -> None:
        self.source_pdf = source_pdf
        self.puts: list[str] = []

    async def copy_to(self, key: ArtifactKey, destination: object) -> None:
        destination.write(self.source_pdf.read_bytes())  # type: ignore[attr-defined]

    async def put(self, key: ArtifactKey, source: object, *, expected_sha256: str) -> None:
        self.puts.append(str(key))


class _Extractor:
    def __init__(self, bundle: ExtractionBundle) -> None:
        self.bundle = bundle
        self.accelerator_device = "cpu"
        self.max_tokens = 256

    def extract(self, source: Path, output_dir: Path) -> ExtractionBundle:
        assert source.is_file()
        output_dir.mkdir(parents=True, exist_ok=True)
        return self.bundle


def _provenance(page_no: int, top: float) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=page_no,
        bbox=BoundingBox(l=10, t=top, r=190, b=top + 10),
        charspan=(0, 20),
    )


def _table_data() -> TableData:
    rows = [
        ("Quantity", "Meaning"),
        ("Force", "push or pull"),
        ("Pressure", "force per area"),
    ]
    cells = [
        TableCell(
            start_row_offset_idx=row_index,
            end_row_offset_idx=row_index + 1,
            start_col_offset_idx=column_index,
            end_col_offset_idx=column_index + 1,
            text=text,
            column_header=row_index == 0,
        )
        for row_index, row in enumerate(rows)
        for column_index, text in enumerate(row)
    ]
    return TableData(table_cells=cells, num_rows=len(rows), num_cols=len(rows[0]))


def _document() -> DoclingDocument:
    document = DoclingDocument(name="cpu-path-fixture")
    document.add_page(page_no=1, size=Size(width=200, height=300))
    document.add_heading("Force and Pressure", level=1, prov=_provenance(1, 10))
    document.add_heading("Definition", level=2, prov=_provenance(1, 30))
    document.add_text(
        DocItemLabel.TEXT,
        "Pressure is force acting per unit area.",
        prov=_provenance(1, 50),
    )
    caption = document.add_text(
        DocItemLabel.CAPTION,
        "Table 1.1 Common physical quantities",
        prov=_provenance(1, 70),
    )
    document.add_table(_table_data(), caption=caption, prov=_provenance(1, 90))
    return document


def _config() -> TextbookChunkingConfig:
    return TextbookChunkingConfig(
        docling_version="fixture-docling",
        tokenizer_revision="fixture-tokenizer-revision",
        child_max_tokens=24,
        parent_soft_tokens=60,
        parent_hard_tokens=100,
    )


@pytest.mark.anyio
async def test_cpu_path_persists_shared_parent_child_graph(tmp_path: Path) -> None:
    work_item = _work_item()
    repository = _Repository(work_item)
    source_pdf = tmp_path / "science.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 fixture")
    docling_json = tmp_path / "docling.json"
    _document().save_as_json(docling_json)
    bundle = ExtractionBundle(
        pages=(),
        assets=(),
        docling_json_path=docling_json,
        page_count=1,
        docling_version="fixture-docling",
        config_fingerprint="e" * 64,
    )
    from tests.extraction.test_textbook_chunking import _TestTokenizer

    chunker = TextbookChunker(
        _config(),
        tokenizer=_TestTokenizer(max_tokens=24),
    )

    @asynccontextmanager
    async def transaction() -> AsyncGenerator[IngestionRepository]:
        yield cast(IngestionRepository, repository)

    service = IngestionService(
        cast(IngestionTransactionFactory, transaction),
        cast(ArtifactStorage, _Storage(source_pdf)),
        extractor=cast(DoclingExtractor, _Extractor(bundle)),
        document_chunker=chunker,
    )

    assert await service.run_once("cpu-worker")
    assert repository.legacy_persist_called is False
    assert repository.persisted is not None
    persisted_work, persisted_bundle, chunking, assets = repository.persisted
    assert persisted_work.ingestion_run.id == work_item.ingestion_run.id
    assert persisted_bundle.docling_json_path == docling_json
    assert chunking.implementation_version == "textbook-hybrid-v3"
    assert chunking.content_units
    assert chunking.chunks
    assert all(chunk.parent_local_id.startswith("U") for chunk in chunking.chunks)
    assert assets == ()
