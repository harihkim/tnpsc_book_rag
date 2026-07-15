"""Tests for guarded metadata-only structlog output."""

import json
import logging
from io import StringIO

import structlog

from tnpsc_book_rag.config import AppEnvironment, LogLevel, Settings
from tnpsc_book_rag.observability import configure_logging, correlation_context, create_telemetry


def make_settings() -> Settings:
    """Build isolated observability settings."""
    return Settings.model_validate(
        {
            "environment": AppEnvironment.TEST,
            "service_name": "observability-test",
            "log_level": LogLevel.INFO,
        }
    )


def test_structlog_adds_allowlisted_correlation_and_trace_ids() -> None:
    """A bound event can be correlated while arbitrary content fields are dropped."""
    settings = make_settings()
    telemetry = create_telemetry(settings)
    stream = StringIO()
    configure_logging(settings, stream=stream)
    logger = structlog.stdlib.get_logger("test.observability")

    with (
        correlation_context(request_id="request-1"),
        telemetry.tracer.start_as_current_span("test-span"),
    ):
        logger.info(
            "request_finished",
            status_code=200,
            query_text="must-not-be-captured",
        )

    telemetry.shutdown()
    payload = json.loads(stream.getvalue())

    assert payload["event"] == "request_finished"
    assert payload["request_id"] == "request-1"
    assert payload["status_code"] == 200
    assert len(payload["trace_id"]) == 32
    assert len(payload["span_id"]) == 16
    assert "query_text" not in payload
    assert "must-not-be-captured" not in json.dumps(payload)


def test_structlog_records_exception_type_without_message() -> None:
    """Exception events exclude potentially sensitive messages and tracebacks."""
    stream = StringIO()
    configure_logging(make_settings(), stream=stream)
    logger = structlog.stdlib.get_logger("test.exception")

    try:
        raise ValueError("sensitive textbook query")
    except ValueError:
        logger.exception("operation_failed")

    payload = json.loads(stream.getvalue())

    assert payload["error_type"] == "builtins.ValueError"
    assert "sensitive textbook query" not in json.dumps(payload)


def test_stdlib_logging_uses_the_same_safe_json_policy() -> None:
    """Third-party stdlib events pass through the guarded processor chain."""
    stream = StringIO()
    configure_logging(make_settings(), stream=stream)

    logging.getLogger("tnpsc.test").info("service_started")
    payload = json.loads(stream.getvalue())

    assert payload["event"] == "service_started"
    assert payload["service"] == "observability-test"
    assert payload["environment"] == "test"


def test_unstructured_stdlib_message_is_redacted() -> None:
    """Free-form dependency messages cannot accidentally expose request content."""
    stream = StringIO()
    configure_logging(make_settings(), stream=stream)

    logging.getLogger("dependency").warning("sensitive textbook query")
    payload = json.loads(stream.getvalue())

    assert payload["event"] == "unstructured_log_redacted"
    assert "sensitive textbook query" not in json.dumps(payload)
