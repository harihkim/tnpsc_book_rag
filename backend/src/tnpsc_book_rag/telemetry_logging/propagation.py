"""Explicit trace and correlation propagation for queued background work."""

from collections.abc import Generator, Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass

from opentelemetry.context import Context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from tnpsc_book_rag.telemetry_logging.context import (
    correlation_context,
    get_correlation_context,
    is_safe_correlation_value,
)

_CARRIER_KEYS = {
    "request_id": "tnpsc-request-id",
    "document_id": "tnpsc-document-id",
    "ingestion_run_id": "tnpsc-ingestion-run-id",
    "stage": "tnpsc-stage",
}
_PROPAGATOR = TraceContextTextMapPropagator()


@dataclass(frozen=True, slots=True)
class ExtractedWorkerContext:
    """Trace parent and allowlisted correlation fields received with a work item."""

    trace_context: Context
    correlation: Mapping[str, str]


def inject_worker_context(carrier: MutableMapping[str, str]) -> None:
    """Add W3C trace context and approved correlation fields to job metadata."""
    _PROPAGATOR.inject(carrier)
    correlation = get_correlation_context()
    for field, carrier_key in _CARRIER_KEYS.items():
        value = correlation.get(field)
        if value is not None:
            carrier[carrier_key] = value


def extract_worker_context(carrier: Mapping[str, str]) -> ExtractedWorkerContext:
    """Read trace and approved correlation fields from untrusted job metadata."""
    correlation = {
        field: value
        for field, carrier_key in _CARRIER_KEYS.items()
        if (value := carrier.get(carrier_key)) is not None and is_safe_correlation_value(value)
    }
    return ExtractedWorkerContext(
        trace_context=_PROPAGATOR.extract(carrier),
        correlation=correlation,
    )


@contextmanager
def use_worker_correlation(context: ExtractedWorkerContext) -> Generator[None]:
    """Bind extracted job correlation fields for the duration of worker handling."""
    with correlation_context(
        request_id=context.correlation.get("request_id"),
        document_id=context.correlation.get("document_id"),
        ingestion_run_id=context.correlation.get("ingestion_run_id"),
        stage=context.correlation.get("stage"),
    ):
        yield
