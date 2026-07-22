"""Structured logging and tracing primitives for the application boundary."""

from tnpsc_book_rag.telemetry_logging.context import (
    correlation_context,
    get_correlation_context,
    run_in_thread_with_context,
)
from tnpsc_book_rag.telemetry_logging.logging import configure_logging
from tnpsc_book_rag.telemetry_logging.middleware import RequestObservabilityMiddleware
from tnpsc_book_rag.telemetry_logging.propagation import (
    ExtractedWorkerContext,
    extract_worker_context,
    inject_worker_context,
    use_worker_correlation,
)
from tnpsc_book_rag.telemetry_logging.telemetry import Telemetry, create_telemetry

__all__ = [
    "ExtractedWorkerContext",
    "RequestObservabilityMiddleware",
    "Telemetry",
    "configure_logging",
    "correlation_context",
    "create_telemetry",
    "extract_worker_context",
    "get_correlation_context",
    "inject_worker_context",
    "run_in_thread_with_context",
    "use_worker_correlation",
]
