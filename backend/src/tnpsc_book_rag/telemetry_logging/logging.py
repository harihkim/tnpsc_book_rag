"""Guarded structlog configuration for metadata-only JSON logs."""

import logging
import re
import sys
from collections.abc import Sequence
from typing import TextIO

import structlog
from opentelemetry import trace
from structlog.contextvars import merge_contextvars
from structlog.stdlib import ProcessorFormatter
from structlog.typing import EventDict, Processor, WrappedLogger

from tnpsc_book_rag.config import Settings

_SAFE_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_LOG_FIELDS = frozenset(
    {
        "timestamp",
        "level",
        "logger",
        "event",
        "service",
        "environment",
        "request_id",
        "document_id",
        "ingestion_run_id",
        "stage",
        "trace_id",
        "span_id",
        "http_method",
        "http_route",
        "status_code",
        "duration_ms",
        "error_code",
        "error_type",
    }
)


def _qualified_exception_type(exception_type: type[BaseException]) -> str:
    """Return a stable exception class name without its message or traceback."""
    return f"{exception_type.__module__}.{exception_type.__qualname__}"


def _exception_type(event_dict: EventDict) -> str | None:
    """Extract only the exception class from structlog or stdlib records."""
    record = event_dict.get("_record")
    if isinstance(record, logging.LogRecord):
        record_exc_info = record.exc_info
        if record_exc_info is not None and record_exc_info[0] is not None:
            return _qualified_exception_type(record_exc_info[0])

    exc_info = event_dict.get("exc_info")
    if isinstance(exc_info, BaseException):
        return _qualified_exception_type(type(exc_info))
    if isinstance(exc_info, tuple) and exc_info and isinstance(exc_info[0], type):
        exception_type = exc_info[0]
        if issubclass(exception_type, BaseException):
            return _qualified_exception_type(exception_type)
    if exc_info is True:
        active_exception_type = sys.exc_info()[0]
        if active_exception_type is not None:
            return _qualified_exception_type(active_exception_type)
    return None


class _SafeMetadataProcessor:
    """Allowlist metadata and replace unstructured messages before JSON rendering."""

    def __init__(self, *, service_name: str, environment: str) -> None:
        self._service_name = service_name
        self._environment = environment

    def __call__(
        self,
        _: WrappedLogger,
        __: str,
        event_dict: EventDict,
    ) -> EventDict:
        exception_type = _exception_type(event_dict)
        event = event_dict.get("event")
        safe_event = (
            event
            if isinstance(event, str) and _SAFE_EVENT_NAME.fullmatch(event)
            else "unstructured_log_redacted"
        )
        payload: EventDict = {key: value for key, value in event_dict.items() if key in _LOG_FIELDS}
        payload["event"] = safe_event
        payload["service"] = self._service_name
        payload["environment"] = self._environment
        if exception_type is not None:
            payload.setdefault("error_type", exception_type)

        # ProcessorFormatter needs these private keys until its final processor chain.
        for key in ("_record", "_from_structlog"):
            if key in event_dict:
                payload[key] = event_dict[key]
        return payload


def _add_trace_context(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Add active OpenTelemetry identifiers without recording span content."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = f"{span_context.trace_id:032x}"
        event_dict["span_id"] = f"{span_context.span_id:016x}"
    return event_dict


def _shared_processors(settings: Settings) -> Sequence[Processor]:
    """Build the common processor chain for application and stdlib events."""
    return (
        merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_trace_context,
        _SafeMetadataProcessor(
            service_name=settings.service_name,
            environment=settings.environment.value,
        ),
    )


def configure_logging(settings: Settings, *, stream: TextIO | None = None) -> None:
    """Configure structlog and stdlib logging with a single safe JSON policy."""
    shared_processors = _shared_processors(settings)
    formatter = ProcessorFormatter(
        processors=(
            ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(sort_keys=True, separators=(",", ":")),
        ),
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.value)

    structlog.configure(
        processors=(*shared_processors, ProcessorFormatter.wrap_for_formatter),
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    for logger_name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True

    logging.getLogger("uvicorn.access").disabled = True
    for logger_name in ("httpx", "httpx2"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    logging.captureWarnings(True)
