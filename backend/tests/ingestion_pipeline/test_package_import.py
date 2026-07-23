"""Tests for importing a verified package-v2 offline extraction."""

import hashlib
import json
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from PIL import Image

import tnpsc_book_rag.ingestion_pipeline.package_import as package_import_module
from tnpsc_book_rag.artifact_storage import ArtifactStorage, ReadableBinary, source_pdf_key
from tnpsc_book_rag.artifact_storage.models import (
    ArtifactKey,
    ArtifactMetadata,
    ArtifactWriteResult,
)
from tnpsc_book_rag.ingestion_pipeline.entities import IngestionRun, IngestionWorkItem
from tnpsc_book_rag.ingestion_pipeline.models import IngestionStage
from tnpsc_book_rag.ingestion_pipeline.package_import import (
    ExtractionPackageImportService,
    IngestionTransactionFactory,
)
from tnpsc_book_rag.ingestion_pipeline.status import IngestionRunStatus
from tnpsc_book_rag.pdf_extraction import ExtractionPackageError
from tnpsc_book_rag.pdf_extraction.docling import ExtractionBundle
from tnpsc_book_rag.pdf_extraction.persistence import StoredAsset
from tnpsc_book_rag.textbook_catalog.entities import Book, BookDocument
from tnpsc_book_rag.textbook_catalog.models import DocumentLanguage, DocumentState
from tnpsc_extraction.models import (
    ChunkContentType,
    ContentUnitType,
    DisplayFormat,
    ExtractedAsset,
    ExtractedBlock,
    ExtractedContentUnit,
    ExtractedPage,
    ExtractedRetrievalChunk,
    TextbookChunkingResult,
)
from tnpsc_extraction.package_writer import (
    asset_payload,
    chunk_payload,
    chunking_manifest,
    content_unit_payload,
    files_manifest,
    json_dump,
    jsonl_dump,
    page_payload,
    write_deterministic_zip,
)
from tnpsc_extraction.textbook_chunking import TextbookChunkingConfig


def _source() -> bytes:
    return b"digital-pdf-source"


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


def _write_package(path: Path, source: bytes) -> None:
    root = path.parent / "package-root"
    root.mkdir()
    image_path = root / "images" / "one.png"
    image_path.parent.mkdir()
    Image.new("RGB", (4, 2), (20, 40, 60)).save(image_path, format="PNG")

    text = "Matter occupies space."
    page = ExtractedPage(
        pdf_page_index=0,
        width=4.0,
        height=2.0,
        raw_text=text,
        normalized_text=text,
        blocks=(ExtractedBlock(text, "prose", 0, None, None),),
        warnings=(),
    )
    asset = ExtractedAsset(
        ordinal=0,
        page_index=0,
        path=image_path,
        media_type="image/png",
        width=4,
        height=2,
        caption="Matter diagram",
        bounding_box=None,
        coordinate_origin=None,
        source_reference="#/pictures/0",
        provenance={"fixture": True},
    )
    parent = ExtractedContentUnit(
        local_id="U000000",
        sequence_number=0,
        unit_type=ContentUnitType.DEFINITION,
        display_text=text,
        display_format=DisplayFormat.PLAIN_TEXT,
        structured_content=None,
        section_path=("Matter",),
        retrieval_eligible=True,
        exclusion_reason=None,
        content_sha256=_parent_sha256(text),
        page_indexes=(0,),
        docling_refs=("#/texts/0",),
        provenance={"fixture": True},
    )
    embedding_text = f"Matter\n{text}"
    child = ExtractedRetrievalChunk(
        local_id="C000000",
        parent_local_id=parent.local_id,
        sequence_number=0,
        display_text=text,
        display_format=DisplayFormat.PLAIN_TEXT,
        embedding_text=embedding_text,
        chapter_title="Matter",
        section_path=("Matter",),
        content_type=ChunkContentType.PROSE,
        token_count=5,
        display_sha256=_text_sha256(text),
        embedding_sha256=_text_sha256(embedding_text),
        page_indexes=(0,),
        docling_refs=("#/texts/0",),
        provenance={"fixture": True},
    )
    config = TextbookChunkingConfig(
        docling_version="2.112.0",
        tokenizer_revision="fixture-tokenizer-revision",
        child_max_tokens=16,
        parent_soft_tokens=32,
        parent_hard_tokens=64,
    )

    json_dump(
        root / "docling.json",
        {
            "texts": [{"self_ref": "#/texts/0", "text": text}],
            "pictures": [{"self_ref": "#/pictures/0"}],
        },
    )
    jsonl_dump(root / "pages.jsonl", [page_payload(page)])
    jsonl_dump(root / "assets.jsonl", [asset_payload(asset, root)])
    jsonl_dump(root / "content_units.jsonl", [content_unit_payload(parent)])
    jsonl_dump(root / "chunks.jsonl", [chunk_payload(child)])
    manifest: dict[str, object] = {
        "manifest_version": 2,
        "created_at": datetime.now(UTC).isoformat(),
        "book": {
            "title": "Standard 6 Science",
            "standard": 6,
            "subject": "Science",
            "term": 1,
            "language": "english",
            "publisher": "Government of Tamil Nadu",
            "edition": "Term I",
        },
        "source": {
            "filename": "science.pdf",
            "sha256": hashlib.sha256(source).hexdigest(),
            "size_bytes": len(source),
        },
        "runtime": {
            "python": "3.13",
            "platform": "fixture-linux",
            "torch": None,
            "cuda_runtime": None,
            "cuda_available": False,
            "cuda_device": None,
        },
        "extraction": {
            "device_requested": "cpu",
            "device_resolved": "cpu",
            "do_table_structure": True,
            "generate_picture_images": True,
            "docling_version": "2.112.0",
            "config_fingerprint": "c" * 64,
        },
        "chunking": chunking_manifest(config),
        "counts": {
            "pages": 1,
            "pages_with_text": 1,
            "content_units": 1,
            "retrieval_eligible_content_units": 1,
            "chunks": 1,
            "assets": 1,
        },
        "files": files_manifest(root),
    }
    json_dump(root / "manifest.json", manifest)
    write_deterministic_zip(root, path)


def _work_item(source: bytes, *, title: str = "Standard 6 Science") -> IngestionWorkItem:
    book_id = uuid4()
    document_id = uuid4()
    now = datetime.now(UTC)
    checksum = hashlib.sha256(source).hexdigest()
    book = Book(
        id=book_id,
        title=title,
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
        source_artifact_key=str(source_pdf_key(checksum)),
        docling_artifact_key=None,
        source_sha256=checksum,
        file_size_bytes=len(source),
        page_count=None,
        state=DocumentState.QUEUED,
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
    return IngestionWorkItem(book=book, document=document, ingestion_run=run)


class _Repository:
    def __init__(self) -> None:
        self.persisted: (
            tuple[
                IngestionWorkItem,
                ExtractionBundle,
                TextbookChunkingResult,
                Sequence[StoredAsset],
            ]
            | None
        ) = None

    async def persist_parent_child_extraction(
        self,
        work_item: IngestionWorkItem,
        bundle: ExtractionBundle,
        chunking: TextbookChunkingResult,
        assets: Sequence[StoredAsset],
        *,
        embedding_batch: object | None = None,
        embedding_generator: object | None = None,
    ) -> None:
        self.persisted = (work_item, bundle, chunking, assets)


class _Storage:
    def __init__(self, source_key: ArtifactKey, source: bytes) -> None:
        self._artifacts = {str(source_key): source}

    async def put(
        self,
        key: ArtifactKey,
        source: ReadableBinary,
        *,
        expected_sha256: str | None = None,
        max_bytes: int | None = None,
    ) -> ArtifactWriteResult:
        value = source.read()
        checksum = hashlib.sha256(value).hexdigest()
        assert expected_sha256 is None or expected_sha256 == checksum
        if max_bytes is not None:
            assert len(value) <= max_bytes
        created = str(key) not in self._artifacts
        existing = self._artifacts.setdefault(str(key), value)
        assert existing == value
        return ArtifactWriteResult(
            artifact=ArtifactMetadata(key=key, size_bytes=len(value), sha256=checksum),
            created=created,
        )

    async def stat(self, key: ArtifactKey) -> ArtifactMetadata:
        value = self._artifacts[str(key)]
        return ArtifactMetadata(
            key=key,
            size_bytes=len(value),
            sha256=hashlib.sha256(value).hexdigest(),
        )


@pytest.mark.anyio
async def test_package_import_persists_v2_artifacts_and_parent_child_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    work_item = _work_item(source)
    package = tmp_path / "science.zip"
    _write_package(package, source)
    storage = _Storage(source_pdf_key(work_item.document.source_sha256), source)
    repository = _Repository()

    async def run_direct(function: Any, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    monkeypatch.setattr(package_import_module, "run_in_thread_with_context", run_direct)

    @asynccontextmanager
    async def transaction() -> AsyncGenerator[_Repository]:
        yield repository

    service = ExtractionPackageImportService(
        cast(IngestionTransactionFactory, transaction),
        cast(ArtifactStorage, storage),
    )
    await service.import_claimed_package(work_item, package)

    assert repository.persisted is not None
    _, bundle, chunking, assets = repository.persisted
    assert bundle.page_count == 1
    assert len(chunking.content_units) == 1
    assert len(chunking.chunks) == 1
    assert chunking.chunks[0].parent_local_id == chunking.content_units[0].local_id
    assert chunking.tokenizer_revision == "fixture-tokenizer-revision"
    assert len(assets) == 1
    assert len(storage._artifacts) == 5


@pytest.mark.anyio
async def test_package_import_rejects_source_identity_mismatch(tmp_path: Path) -> None:
    source = _source()
    work_item = _work_item(b"different-source")
    package = tmp_path / "science.zip"
    _write_package(package, source)
    storage = _Storage(source_pdf_key(work_item.document.source_sha256), b"different-source")

    with pytest.raises(ExtractionPackageError, match="source checksum"):
        await ExtractionPackageImportService(
            cast(IngestionTransactionFactory, lambda: None),
            cast(ArtifactStorage, storage),
        ).import_claimed_package(work_item, package)


@pytest.mark.anyio
async def test_package_import_rejects_catalog_metadata_mismatch(tmp_path: Path) -> None:
    source = _source()
    work_item = _work_item(source, title="Different catalog title")
    package = tmp_path / "science.zip"
    _write_package(package, source)
    storage = _Storage(source_pdf_key(work_item.document.source_sha256), source)

    with pytest.raises(ExtractionPackageError, match="title does not match"):
        await ExtractionPackageImportService(
            cast(IngestionTransactionFactory, lambda: None),
            cast(ArtifactStorage, storage),
        ).import_claimed_package(work_item, package)
