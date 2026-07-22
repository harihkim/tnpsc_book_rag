"""Tests for metadata-only extraction stage tracing."""

from uuid import uuid4

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from tnpsc_book_rag.config import AppEnvironment, Settings
from tnpsc_book_rag.ingestion_pipeline.service import _ingestion_span
from tnpsc_book_rag.telemetry_logging import create_telemetry, get_correlation_context


def make_settings(**overrides: object) -> Settings:
    """Build isolated test settings without reading the developer environment."""
    values: dict[str, object] = {
        "environment": AppEnvironment.TEST,
        "service_name": "ingestion-observability-test",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_extraction_stage_span_contains_only_bounded_metadata() -> None:
    """Extraction traces carry IDs and counts, never document content."""
    exporter = InMemorySpanExporter()
    telemetry = create_telemetry(make_settings(), span_exporter=exporter)
    document_id = uuid4()
    ingestion_run_id = uuid4()

    with _ingestion_span(
        telemetry.tracer,
        "ingestion.extract",
        document_id=document_id,
        ingestion_run_id=ingestion_run_id,
        stage="extraction",
    ) as span:
        span.set_attribute("extraction.page_count", 108)
        assert get_correlation_context() == {
            "document_id": str(document_id),
            "ingestion_run_id": str(ingestion_run_id),
            "stage": "extraction",
        }

    spans = exporter.get_finished_spans()
    telemetry.shutdown()

    assert len(spans) == 1
    recorded = spans[0]
    assert recorded.name == "ingestion.extract"
    assert recorded.attributes is not None
    assert recorded.attributes["document.id"] == str(document_id)
    assert recorded.attributes["ingestion_run.id"] == str(ingestion_run_id)
    assert recorded.attributes["ingestion.stage"] == "extraction"
    assert recorded.attributes["extraction.page_count"] == 108
    assert "textbook content" not in str(recorded.attributes)


def test_stage_span_records_error_type_without_exception_content() -> None:
    """Stage failures are traceable by type while exception messages stay private."""
    exporter = InMemorySpanExporter()
    telemetry = create_telemetry(make_settings(), span_exporter=exporter)

    with (
        pytest.raises(ValueError, match="sensitive textbook content"),
        _ingestion_span(
            telemetry.tracer,
            "ingestion.chunk",
            document_id=uuid4(),
            ingestion_run_id=uuid4(),
            stage="chunking",
        ),
    ):
        raise ValueError("sensitive textbook content")

    spans = exporter.get_finished_spans()
    telemetry.shutdown()

    assert len(spans) == 1
    recorded = spans[0]
    assert recorded.status.status_code is StatusCode.ERROR
    assert recorded.attributes is not None
    assert recorded.attributes["error.type"] == "builtins.ValueError"
    assert "sensitive textbook content" not in str(recorded.attributes)
    assert recorded.events == ()
