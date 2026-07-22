"""Tests for queued-worker trace and correlation propagation."""

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tnpsc_book_rag.config import AppEnvironment, Settings
from tnpsc_book_rag.telemetry_logging import (
    correlation_context,
    create_telemetry,
    extract_worker_context,
    get_correlation_context,
    inject_worker_context,
    use_worker_correlation,
)


def test_worker_carrier_preserves_trace_parent_and_allowlisted_correlation() -> None:
    """A queued job can continue its producer trace without serializing live context."""
    settings = Settings.model_validate(
        {"environment": AppEnvironment.TEST, "service_name": "worker-test"}
    )
    exporter = InMemorySpanExporter()
    telemetry = create_telemetry(settings, span_exporter=exporter)
    carrier: dict[str, str] = {}

    with (
        correlation_context(
            request_id="request-1",
            document_id="00000000-0000-0000-0000-000000000001",
            stage="queued",
        ),
        telemetry.tracer.start_as_current_span("producer") as producer_span,
    ):
        producer_span_id = producer_span.get_span_context().span_id
        inject_worker_context(carrier)

    extracted = extract_worker_context(carrier)
    with (
        use_worker_correlation(extracted),
        telemetry.tracer.start_as_current_span(
            "worker",
            context=extracted.trace_context,
        ),
    ):
        worker_correlation = dict(get_correlation_context())

    spans = {span.name: span for span in exporter.get_finished_spans()}
    telemetry.shutdown()

    assert "traceparent" in carrier
    assert carrier["tnpsc-request-id"] == "request-1"
    assert worker_correlation == {
        "request_id": "request-1",
        "document_id": "00000000-0000-0000-0000-000000000001",
        "stage": "queued",
    }
    assert spans["worker"].parent is not None
    assert spans["worker"].parent.span_id == producer_span_id


def test_worker_carrier_drops_untrusted_correlation_content() -> None:
    """Free-form values received from a queue are not rebound into logs."""
    extracted = extract_worker_context({"tnpsc-stage": "copied textbook content"})

    assert extracted.correlation == {}
