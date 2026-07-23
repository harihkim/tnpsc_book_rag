"""Stable public response snapshots used for durable idempotent replay."""

import hashlib
import json
from datetime import datetime
from typing import cast
from uuid import UUID

from tnpsc_book_rag.artifact_storage.keys import source_pdf_key
from tnpsc_book_rag.ingestion_pipeline.entities import IngestionRun
from tnpsc_book_rag.ingestion_pipeline.models import IngestionStage
from tnpsc_book_rag.ingestion_pipeline.status import IngestionRunStatus
from tnpsc_book_rag.textbook_catalog.entities import BookDocument
from tnpsc_book_rag.textbook_catalog.models import CatalogStatus, DocumentLanguage, DocumentState
from tnpsc_book_rag.textbook_catalog.mutations import AcceptedDocumentUpload
from tnpsc_book_rag.textbook_catalog.read_models import CatalogBook


def canonical_hash(payload: dict[str, object]) -> str:
    """Return the deterministic request fingerprint persisted with a client key."""
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _datetime(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("stored response integer is invalid")
    return value


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("stored response object is invalid")
    return cast(dict[str, object], value)


def book_payload(book: CatalogBook) -> dict[str, object]:
    """Serialize the complete public book response without infrastructure fields."""
    return {
        "id": str(book.id),
        "title": book.title,
        "standard": book.standard,
        "subject": book.subject,
        "language": book.language.value,
        "publisher": book.publisher,
        "catalog_identifier": book.catalog_identifier,
        "catalog_status": book.catalog_status.value,
        "document_count": book.document_count,
        "active_document_id": (
            None if book.active_document_id is None else str(book.active_document_id)
        ),
        "latest_document_id": (
            None if book.latest_document_id is None else str(book.latest_document_id)
        ),
        "latest_document_state": (
            None if book.latest_document_state is None else book.latest_document_state.value
        ),
        "created_at": book.created_at.isoformat(),
        "updated_at": book.updated_at.isoformat(),
    }


def book_from_payload(payload: dict[str, object]) -> CatalogBook:
    """Rehydrate a validated internal book projection from a stored response."""
    active_id = payload["active_document_id"]
    latest_id = payload["latest_document_id"]
    latest_state = payload["latest_document_state"]
    return CatalogBook(
        id=UUID(str(payload["id"])),
        title=str(payload["title"]),
        standard=_integer(payload["standard"]),
        subject=str(payload["subject"]),
        language=DocumentLanguage(str(payload["language"])),
        publisher=str(payload["publisher"]),
        catalog_identifier=(
            None if payload["catalog_identifier"] is None else str(payload["catalog_identifier"])
        ),
        catalog_status=CatalogStatus(str(payload["catalog_status"])),
        document_count=_integer(payload["document_count"]),
        active_document_id=None if active_id is None else UUID(str(active_id)),
        latest_document_id=None if latest_id is None else UUID(str(latest_id)),
        latest_document_state=(None if latest_state is None else DocumentState(str(latest_state))),
        created_at=_datetime(payload["created_at"]),
        updated_at=_datetime(payload["updated_at"]),
    )


def _document_payload(document: BookDocument) -> dict[str, object]:
    return {
        "id": str(document.id),
        "book_id": str(document.book_id),
        "edition": document.edition,
        "source_filename": document.source_filename,
        "media_type": document.media_type,
        "source_sha256": document.source_sha256,
        "file_size_bytes": document.file_size_bytes,
        "page_count": document.page_count,
        "state": document.state.value,
        "activated_at": (
            None if document.activated_at is None else document.activated_at.isoformat()
        ),
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def _document_from_payload(payload: dict[str, object]) -> BookDocument:
    activated_at = payload["activated_at"]
    source_sha256 = str(payload["source_sha256"])
    return BookDocument(
        id=UUID(str(payload["id"])),
        book_id=UUID(str(payload["book_id"])),
        edition=str(payload["edition"]),
        source_filename=str(payload["source_filename"]),
        media_type=str(payload["media_type"]),
        source_artifact_key=str(source_pdf_key(source_sha256)),
        docling_artifact_key=None,
        source_sha256=source_sha256,
        file_size_bytes=_integer(payload["file_size_bytes"]),
        page_count=(None if payload["page_count"] is None else _integer(payload["page_count"])),
        state=DocumentState(str(payload["state"])),
        activated_at=None if activated_at is None else _datetime(activated_at),
        created_at=_datetime(payload["created_at"]),
        updated_at=_datetime(payload["updated_at"]),
    )


def _ingestion_payload(run: IngestionRun) -> dict[str, object]:
    return {
        "id": str(run.id),
        "document_id": str(run.document_id),
        "status": run.status.value,
        "current_stage": run.current_stage.value,
        "retry_count": run.retry_count,
        "started_at": None if run.started_at is None else run.started_at.isoformat(),
        "completed_at": None if run.completed_at is None else run.completed_at.isoformat(),
        "warnings": list(run.warnings),
        "error": run.error,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def _ingestion_from_payload(payload: dict[str, object]) -> IngestionRun:
    started_at = payload["started_at"]
    completed_at = payload["completed_at"]
    raw_warnings = payload["warnings"]
    if not isinstance(raw_warnings, list):
        raise ValueError("stored ingestion warnings are invalid")
    warnings = tuple(_mapping(warning) for warning in raw_warnings)
    raw_error = payload["error"]
    error = None if raw_error is None else _mapping(raw_error)
    return IngestionRun(
        id=UUID(str(payload["id"])),
        document_id=UUID(str(payload["document_id"])),
        status=IngestionRunStatus(str(payload["status"])),
        current_stage=IngestionStage(str(payload["current_stage"])),
        retry_count=_integer(payload["retry_count"]),
        started_at=None if started_at is None else _datetime(started_at),
        completed_at=None if completed_at is None else _datetime(completed_at),
        warnings=warnings,
        error=error,
        created_at=_datetime(payload["created_at"]),
        updated_at=_datetime(payload["updated_at"]),
    )


def upload_payload(upload: AcceptedDocumentUpload) -> dict[str, object]:
    """Serialize the complete public upload-acceptance response."""
    return {
        "document": _document_payload(upload.document),
        "ingestion_run": _ingestion_payload(upload.ingestion_run),
        "poll_after_seconds": upload.poll_after_seconds,
        "links": {
            "document": upload.document_url,
            "ingestion_run": upload.ingestion_run_url,
        },
    }


def upload_from_payload(payload: dict[str, object]) -> AcceptedDocumentUpload:
    """Rehydrate an accepted upload from a stored public response."""
    document_payload = _mapping(payload["document"])
    ingestion_payload = _mapping(payload["ingestion_run"])
    links = _mapping(payload["links"])
    return AcceptedDocumentUpload(
        document=_document_from_payload(document_payload),
        ingestion_run=_ingestion_from_payload(ingestion_payload),
        poll_after_seconds=_integer(payload["poll_after_seconds"]),
        document_url=str(links["document"]),
        ingestion_run_url=str(links["ingestion_run"]),
    )
