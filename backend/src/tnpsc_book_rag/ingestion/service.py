"""One-document extraction orchestration for the Phase 1 worker."""

import hashlib
import os
from collections.abc import Callable, Generator
from contextlib import AbstractAsyncContextManager, contextmanager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import structlog
from opentelemetry.trace import Span, Status, StatusCode, Tracer, get_tracer
from PIL import Image

from tnpsc_book_rag.extraction import DoclingExtractor, StoredAsset, chunk_pages
from tnpsc_book_rag.ingestion.entities import IngestionWorkItem
from tnpsc_book_rag.ingestion.ports import IngestionRepository
from tnpsc_book_rag.observability import correlation_context, run_in_thread_with_context
from tnpsc_book_rag.storage import ArtifactStorage
from tnpsc_book_rag.storage.keys import docling_json_key, image_asset_key, thumbnail_asset_key
from tnpsc_book_rag.storage.models import ArtifactKey

type IngestionTransactionFactory = Callable[[], AbstractAsyncContextManager[IngestionRepository]]
_LOGGER = structlog.stdlib.get_logger(__name__)


class IngestionService:
    """Claim, extract, persist, and fail one queued PDF at a time."""

    def __init__(
        self,
        transactions: IngestionTransactionFactory,
        storage: ArtifactStorage,
        *,
        extractor: DoclingExtractor | None = None,
        thumbnail_max_edge_pixels: int = 640,
        tracer: Tracer | None = None,
    ) -> None:
        self._transactions = transactions
        self._storage = storage
        self._extractor = extractor or DoclingExtractor()
        self._thumbnail_max_edge_pixels = thumbnail_max_edge_pixels
        self._tracer = tracer or get_tracer("tnpsc_book_rag.ingestion")

    async def run_once(self, worker_id: str | None = None) -> bool:
        """Process the oldest queued run, returning whether work was claimed."""
        worker_id = worker_id or f"worker-{os.getpid()}"
        async with self._transactions() as repository:
            work_item = await repository.claim_next_ingestion_run(worker_id)
        if work_item is None:
            return False
        with _ingestion_span(
            self._tracer,
            "ingestion.run",
            document_id=work_item.document.id,
            ingestion_run_id=work_item.ingestion_run.id,
            stage="ingestion",
        ) as span:
            try:
                await self._extract_and_persist(work_item)
            except Exception as error:
                _mark_span_error(span, error)
                code = (
                    error.code
                    if hasattr(error, "code") and isinstance(error.code, str)
                    else "extraction_failed"
                )
                message = (
                    "the PDF could not be converted into a usable digital document"
                    if code == "unsupported_document"
                    else "the ingestion worker failed while processing the document"
                )
                _LOGGER.error(
                    "ingestion_failed",
                    document_id=str(work_item.document.id),
                    ingestion_run_id=str(work_item.ingestion_run.id),
                    error_code=code,
                    error_type=f"{type(error).__module__}.{type(error).__qualname__}",
                )
                try:
                    async with self._transactions() as repository:
                        await repository.mark_ingestion_failed(
                            work_item.ingestion_run.id,
                            code=code,
                            message=message,
                            completed_at=datetime.now(UTC),
                        )
                except Exception:
                    # Keep the worker alive without exposing the original failure details.
                    _LOGGER.exception("ingestion_failure_state_update_failed")
                return True
        return True

    async def _extract_and_persist(self, work_item: IngestionWorkItem) -> None:
        document = work_item.document
        run = work_item.ingestion_run
        with (
            correlation_context(document_id=document.id, ingestion_run_id=run.id),
            TemporaryDirectory(prefix=f"tnpsc-extraction-{document.id}-") as temporary,
        ):
            root = Path(temporary)
            source_path = root / "source.pdf"
            with source_path.open("w+b") as source_file:
                await self._storage.copy_to(ArtifactKey(document.source_artifact_key), source_file)
            extraction_dir = root / "extracted"
            with _ingestion_span(
                self._tracer,
                "ingestion.extract",
                document_id=document.id,
                ingestion_run_id=run.id,
                stage="extraction",
            ) as span:
                bundle = await run_in_thread_with_context(
                    self._extractor.extract,
                    source_path,
                    extraction_dir,
                )
                span.set_attribute("extraction.device", self._extractor.accelerator_device)
                span.set_attribute("extraction.page_count", bundle.page_count)
                span.set_attribute("extraction.asset_count", len(bundle.assets))
                span.set_attribute("extraction.docling_version", bundle.docling_version)

            with _ingestion_span(
                self._tracer,
                "ingestion.chunk",
                document_id=document.id,
                ingestion_run_id=run.id,
                stage="chunking",
            ) as span:
                chunks = chunk_pages(bundle.pages, max_tokens=self._extractor.max_tokens)
                span.set_attribute("chunk.count", len(chunks))

            with _ingestion_span(
                self._tracer,
                "ingestion.store_docling",
                document_id=document.id,
                ingestion_run_id=run.id,
                stage="artifact_storage",
            ) as span:
                docling_checksum = hashlib.sha256(bundle.docling_json_path.read_bytes()).hexdigest()
                with bundle.docling_json_path.open("rb") as docling_file:
                    await self._storage.put(
                        docling_json_key(document.id, run.id),
                        docling_file,
                        expected_sha256=docling_checksum,
                    )
                span.set_attribute("artifact.kind", "docling_json")

            with _ingestion_span(
                self._tracer,
                "ingestion.store_assets",
                document_id=document.id,
                ingestion_run_id=run.id,
                stage="artifact_storage",
            ) as span:
                stored_assets = []
                for asset in bundle.assets:
                    source_checksum = hashlib.sha256(asset.path.read_bytes()).hexdigest()
                    source_key = image_asset_key(source_checksum, asset.media_type)
                    with asset.path.open("rb") as image_file:
                        await self._storage.put(
                            source_key,
                            image_file,
                            expected_sha256=source_checksum,
                        )
                    thumbnail_key, thumbnail_width, thumbnail_height = await self._store_thumbnail(
                        asset.path
                    )
                    stored_assets.append(
                        StoredAsset(
                            source=asset,
                            artifact_key=source_key,
                            sha256=source_checksum,
                            thumbnail_artifact_key=thumbnail_key,
                            thumbnail_width=thumbnail_width,
                            thumbnail_height=thumbnail_height,
                        )
                    )
                span.set_attribute("asset.count", len(stored_assets))

            with _ingestion_span(
                self._tracer,
                "ingestion.persist",
                document_id=document.id,
                ingestion_run_id=run.id,
                stage="persistence",
            ) as span:
                async with self._transactions() as repository:
                    await repository.persist_extraction(work_item, bundle, chunks, stored_assets)
                span.set_attribute("chunk.count", len(chunks))
                span.set_attribute("asset.count", len(stored_assets))

    async def _store_thumbnail(
        self,
        source: Path,
    ) -> tuple[ArtifactKey, int, int]:
        thumbnail_bytes, thumbnail_width, thumbnail_height = await run_in_thread_with_context(
            _build_thumbnail,
            source,
            self._thumbnail_max_edge_pixels,
        )
        checksum = hashlib.sha256(thumbnail_bytes).hexdigest()
        key = thumbnail_asset_key(checksum)
        await self._storage.put(key, BytesIO(thumbnail_bytes), expected_sha256=checksum)
        return key, thumbnail_width, thumbnail_height


@contextmanager
def _ingestion_span(
    tracer: Tracer,
    name: str,
    *,
    document_id: UUID,
    ingestion_run_id: UUID,
    stage: str,
) -> Generator[Span]:
    """Create a metadata-only stage span with bounded correlation context."""
    with (
        correlation_context(
            document_id=document_id,
            ingestion_run_id=ingestion_run_id,
            stage=stage,
        ),
        tracer.start_as_current_span(
            name,
            record_exception=False,
            set_status_on_exception=False,
        ) as span,
    ):
        span.set_attribute("document.id", str(document_id))
        span.set_attribute("ingestion_run.id", str(ingestion_run_id))
        span.set_attribute("ingestion.stage", stage)
        try:
            yield span
        except Exception as error:
            _mark_span_error(span, error)
            raise


def _mark_span_error(span: Span, error: Exception) -> None:
    """Mark a span with a safe exception type without recording content or traceback."""
    span.set_status(Status(StatusCode.ERROR))
    span.set_attribute("error.type", f"{type(error).__module__}.{type(error).__qualname__}")


def _build_thumbnail(source: Path, max_edge_pixels: int) -> tuple[bytes, int, int]:
    """Create a canonical PNG thumbnail in the worker thread."""
    with Image.open(source) as image:
        thumbnail = image.copy()
        thumbnail.thumbnail((max_edge_pixels, max_edge_pixels), Image.Resampling.LANCZOS)
        output = BytesIO()
        thumbnail.save(output, format="PNG", optimize=True)
        return output.getvalue(), thumbnail.width, thumbnail.height
