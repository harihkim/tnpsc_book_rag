"""Import verified offline extraction packages into application storage and PostgreSQL."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from io import BytesIO
from pathlib import Path
from uuid import UUID

import structlog
from PIL import Image

from tnpsc_book_rag.extraction import (
    ExtractionPackageError,
    MaterializedExtractionPackage,
    StoredAsset,
    materialize_extraction_package,
)
from tnpsc_book_rag.ingestion.entities import IngestionWorkItem
from tnpsc_book_rag.ingestion.ports import IngestionRepository
from tnpsc_book_rag.observability import correlation_context, run_in_thread_with_context
from tnpsc_book_rag.storage import ArtifactStorage
from tnpsc_book_rag.storage.keys import (
    docling_json_key,
    extraction_package_key,
    image_asset_key,
    thumbnail_asset_key,
)
from tnpsc_book_rag.storage.models import ArtifactKey

type IngestionTransactionFactory = Callable[[], AbstractAsyncContextManager[IngestionRepository]]
_LOGGER = structlog.stdlib.get_logger(__name__)


class ExtractionPackageImportService:
    """Persist one claimed, offline-extracted package as an ordinary ingestion result.

    The source PDF is intentionally checked in its existing content-addressed location rather
    than copied out of the package.  The ZIP itself is retained under a deterministic run key for
    audit/replay, while PostgreSQL receives the package-v2 semantic parents, retrieval children,
    pages, and asset metadata in one transaction.
    """

    def __init__(
        self,
        transactions: IngestionTransactionFactory,
        storage: ArtifactStorage,
        *,
        thumbnail_max_edge_pixels: int = 640,
        embedding_generator: object | None = None,
    ) -> None:
        if thumbnail_max_edge_pixels <= 0:
            raise ValueError("thumbnail maximum edge must be positive")
        self._transactions = transactions
        self._storage = storage
        self._thumbnail_max_edge_pixels = thumbnail_max_edge_pixels
        self._embedding_generator = embedding_generator

    async def import_claimed_package(
        self,
        work_item: IngestionWorkItem,
        archive_path: Path,
    ) -> None:
        """Verify, store, and persist a package for an already claimed ingestion run."""
        document = work_item.document
        run = work_item.ingestion_run
        with (
            correlation_context(
                document_id=document.id,
                ingestion_run_id=run.id,
                stage="extraction",
            ),
            materialize_extraction_package(archive_path) as materialized,
        ):
            self._check_document_source(materialized, work_item)
            await self._check_stored_source(work_item)
            await self._store_package(materialized.package.archive_path, document.id, run.id)
            await self._store_docling(materialized, document.id, run.id)
            stored_assets = await self._store_assets(materialized)

            # Generate embeddings if embedding generator is configured
            embedding_batch = None
            if self._embedding_generator is not None and materialized.chunking.chunks:
                embedding_texts = [
                    chunk.embedding_text for chunk in materialized.chunking.chunks
                ]
                embedding_batch = await run_in_thread_with_context(
                    self._embedding_generator.embed_texts,  # type: ignore[union-attr]
                    embedding_texts,
                )

            async with self._transactions() as repository:
                await repository.persist_parent_child_extraction(
                    work_item,
                    materialized.bundle,
                    materialized.chunking,
                    stored_assets,
                    embedding_batch=embedding_batch,
                    embedding_generator=self._embedding_generator,
                )
        _LOGGER.info(
            "extraction_package_imported",
            document_id=str(document.id),
            ingestion_run_id=str(run.id),
            page_count=materialized.package.page_count,
            content_unit_count=materialized.package.content_unit_count,
            chunk_count=materialized.package.chunk_count,
            asset_count=materialized.package.asset_count,
        )

    @staticmethod
    def _check_document_source(
        materialized: MaterializedExtractionPackage,
        work_item: IngestionWorkItem,
    ) -> None:
        package = materialized.package
        book = work_item.book
        document = work_item.document
        if book.id != document.book_id:
            raise ExtractionPackageError("claimed catalog book does not own the document")
        catalog_values = {
            "title": book.title,
            "standard": book.standard,
            "subject": book.subject,
            "language": book.language.value,
            "publisher": book.publisher,
        }
        package_values = {
            "title": package.book.title,
            "standard": package.book.standard,
            "subject": package.book.subject,
            "language": package.book.language,
            "publisher": package.book.publisher,
        }
        for field, expected in catalog_values.items():
            if package_values[field] != expected:
                raise ExtractionPackageError(f"package {field} does not match the catalog book")
        if package.source_sha256 != document.source_sha256:
            raise ExtractionPackageError("package source checksum does not match the document")
        if package.source_size_bytes != document.file_size_bytes:
            raise ExtractionPackageError("package source size does not match the document")
        if package.book.edition != document.edition:
            raise ExtractionPackageError("package edition does not match the document")

    async def _check_stored_source(self, work_item: IngestionWorkItem) -> None:
        document = work_item.document
        stored = await self._storage.stat(ArtifactKey(document.source_artifact_key))
        if stored.sha256 != document.source_sha256 or stored.size_bytes != document.file_size_bytes:
            raise ExtractionPackageError("stored source failed checksum or size verification")

    async def _store_package(self, archive_path: Path, document_id: UUID, run_id: UUID) -> None:
        checksum = await run_in_thread_with_context(_sha256_file, archive_path)
        key = extraction_package_key(document_id, run_id)
        with archive_path.open("rb") as archive:
            await self._storage.put(key, archive, expected_sha256=checksum)

    async def _store_docling(
        self,
        materialized: MaterializedExtractionPackage,
        document_id: UUID,
        run_id: UUID,
    ) -> None:
        path = materialized.bundle.docling_json_path
        checksum = await run_in_thread_with_context(_sha256_file, path)
        key = docling_json_key(document_id, run_id)
        with path.open("rb") as docling:
            await self._storage.put(key, docling, expected_sha256=checksum)

    async def _store_assets(
        self,
        materialized: MaterializedExtractionPackage,
    ) -> list[StoredAsset]:
        stored_assets: list[StoredAsset] = []
        for asset in materialized.bundle.assets:
            checksum = await run_in_thread_with_context(_sha256_file, asset.path)
            source_key = image_asset_key(checksum, asset.media_type)
            with asset.path.open("rb") as image_file:
                await self._storage.put(source_key, image_file, expected_sha256=checksum)
            thumbnail_bytes, width, height = await run_in_thread_with_context(
                _build_thumbnail,
                asset.path,
                self._thumbnail_max_edge_pixels,
            )
            thumbnail_checksum = hashlib.sha256(thumbnail_bytes).hexdigest()
            thumbnail_key = thumbnail_asset_key(thumbnail_checksum)
            await self._storage.put(
                thumbnail_key,
                BytesIO(thumbnail_bytes),
                expected_sha256=thumbnail_checksum,
            )
            stored_assets.append(
                StoredAsset(
                    source=asset,
                    artifact_key=source_key,
                    sha256=checksum,
                    thumbnail_artifact_key=thumbnail_key,
                    thumbnail_width=width,
                    thumbnail_height=height,
                )
            )
        return stored_assets


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _build_thumbnail(source: Path, max_edge_pixels: int) -> tuple[bytes, int, int]:
    """Create a canonical PNG thumbnail in a context-propagating worker thread."""
    with Image.open(source) as image:
        thumbnail = image.copy()
        thumbnail.thumbnail((max_edge_pixels, max_edge_pixels), Image.Resampling.LANCZOS)
        output = BytesIO()
        thumbnail.save(output, format="PNG", optimize=True)
        return output.getvalue(), thumbnail.width, thumbnail.height


__all__ = ["ExtractionPackageImportService"]
