"""Tests for OpenTelemetry setup and metadata-only HTTP instrumentation."""

import json
import re
from io import StringIO

import pytest
from fastapi import Response
from httpx2 import ASGITransport, AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from starlette.middleware.cors import CORSMiddleware
from starlette.types import Message, Receive, Scope, Send

from tnpsc_book_rag.config import AppEnvironment, Settings
from tnpsc_book_rag.main import create_app
from tnpsc_book_rag.observability import (
    RequestObservabilityMiddleware,
    configure_logging,
    create_telemetry,
)


def make_settings(**overrides: object) -> Settings:
    """Build isolated settings with optional observability overrides."""
    values: dict[str, object] = {
        "environment": AppEnvironment.TEST,
        "service_name": "telemetry-test",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_disabled_telemetry_uses_no_sdk_provider() -> None:
    """Tracing can be disabled without changing application call sites."""
    telemetry = create_telemetry(make_settings(otel_enabled=False))

    assert telemetry.provider is None
    telemetry.shutdown()


def test_otlp_endpoint_creates_an_exporting_provider() -> None:
    """An explicit OTLP/HTTP traces endpoint enables batch export configuration."""
    telemetry = create_telemetry(
        make_settings(otel_traces_endpoint="http://collector:4318/v1/traces")
    )

    assert telemetry.provider is not None
    telemetry.shutdown()


@pytest.mark.anyio
async def test_http_request_has_request_id_and_metadata_only_span() -> None:
    """HTTP tracing preserves correlation while excluding query-string content."""
    exporter = InMemorySpanExporter()
    telemetry = create_telemetry(make_settings(), span_exporter=exporter)
    application = create_app(make_settings(), telemetry=telemetry)

    async def search() -> dict[str, str]:
        return {"status": "ok"}

    application.add_api_route("/search", search, methods=["GET"])
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/search?query=sensitive-textbook-question",
            headers={"x-request-id": "request-123"},
        )

    spans = exporter.get_finished_spans()
    telemetry.shutdown()

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "request-123"
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes is not None
    assert span.name == "GET /search"
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["http.route"] == "/search"
    assert span.attributes["http.response.status_code"] == 200
    assert span.resource.attributes["service.name"] == "telemetry-test"
    assert "sensitive-textbook-question" not in str(span.attributes)


@pytest.mark.anyio
async def test_invalid_request_id_is_replaced() -> None:
    """Unbounded or unsafe inbound correlation values are never reflected."""
    telemetry = create_telemetry(make_settings())
    application = create_app(make_settings(), telemetry=telemetry)
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/health/live",
            headers={"x-request-id": "unsafe request id"},
        )

    telemetry.shutdown()

    assert response.headers["x-request-id"] != "unsafe request id"
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


@pytest.mark.anyio
async def test_successful_health_probe_emits_no_span_or_access_event() -> None:
    """High-frequency successful probes remain quiet while retaining request IDs."""
    settings = make_settings()
    exporter = InMemorySpanExporter()
    telemetry = create_telemetry(settings, span_exporter=exporter)
    stream = StringIO()
    configure_logging(settings, stream=stream)
    application = create_app(settings, telemetry=telemetry)
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health/live", headers={"x-request-id": "probe-1"})

    telemetry.shutdown()

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "probe-1"
    assert exporter.get_finished_spans() == ()
    assert stream.getvalue() == ""


@pytest.mark.anyio
async def test_failed_health_probe_is_logged_without_creating_a_span() -> None:
    """A failed quiet route remains visible as a structured failure event."""
    settings = make_settings()
    exporter = InMemorySpanExporter()
    telemetry = create_telemetry(settings, span_exporter=exporter)
    stream = StringIO()
    configure_logging(settings, stream=stream)
    application = create_app(settings, telemetry=telemetry)

    async def not_ready() -> Response:
        return Response(status_code=503)

    application.add_api_route("/health/ready", not_ready, methods=["GET"])
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health/ready")

    telemetry.shutdown()
    payload = json.loads(stream.getvalue())

    assert response.status_code == 503
    assert exporter.get_finished_spans() == ()
    assert payload["event"] == "http_probe_failed"
    assert payload["http_route"] == "/health/ready"
    assert payload["status_code"] == 503


@pytest.mark.anyio
async def test_unhandled_health_probe_failure_is_logged_without_span() -> None:
    """Unhandled failures on quiet routes still produce the safe generic response."""
    settings = make_settings()
    exporter = InMemorySpanExporter()
    telemetry = create_telemetry(settings, span_exporter=exporter)
    stream = StringIO()
    configure_logging(settings, stream=stream)
    application = create_app(settings, telemetry=telemetry)

    async def fail_readiness() -> None:
        raise RuntimeError("sensitive readiness detail")

    application.add_api_route("/health/ready", fail_readiness, methods=["GET"])
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health/ready")

    telemetry.shutdown()
    payload = json.loads(stream.getvalue())

    assert response.status_code == 500
    assert exporter.get_finished_spans() == ()
    assert payload["event"] == "http_request_failed"
    assert payload["error_type"] == "builtins.RuntimeError"
    assert "sensitive readiness detail" not in stream.getvalue()


@pytest.mark.anyio
async def test_unhandled_error_span_excludes_exception_content() -> None:
    """Unhandled exceptions record only their type, not message or stack trace."""
    exporter = InMemorySpanExporter()
    telemetry = create_telemetry(make_settings(), span_exporter=exporter)
    application = create_app(make_settings(), telemetry=telemetry)

    async def fail() -> None:
        raise RuntimeError("sensitive query must not enter telemetry")

    application.add_api_route("/failure", fail, methods=["GET"])
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/failure", headers={"x-request-id": "failure-1"})

    spans = exporter.get_finished_spans()
    telemetry.shutdown()

    assert len(spans) == 1
    span = spans[0]
    assert response.status_code == 500
    assert response.headers["x-request-id"] == "failure-1"
    assert response.json() == {
        "detail": "Internal server error",
        "error_code": "internal_server_error",
        "request_id": "failure-1",
    }
    assert span.attributes is not None
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes["error.type"] == "builtins.RuntimeError"
    assert span.events == ()
    assert "sensitive query" not in str(span.attributes)


@pytest.mark.anyio
async def test_server_error_response_marks_span_as_error() -> None:
    """A handled 5xx response is represented as a failed server span."""
    exporter = InMemorySpanExporter()
    telemetry = create_telemetry(make_settings(), span_exporter=exporter)
    application = create_app(make_settings(), telemetry=telemetry)

    async def unavailable() -> Response:
        return Response(status_code=503)

    application.add_api_route("/unavailable", unavailable, methods=["GET"])
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/unavailable")

    spans = exporter.get_finished_spans()
    telemetry.shutdown()

    assert response.status_code == 503
    assert len(spans) == 1
    assert spans[0].status.status_code is StatusCode.ERROR


@pytest.mark.anyio
async def test_error_after_response_start_is_not_replaced_with_second_response() -> None:
    """Streaming failures are recorded and re-raised once headers are on the wire."""
    exporter = InMemorySpanExporter()
    telemetry = create_telemetry(make_settings(), span_exporter=exporter)

    async def partial_failure(_: Scope, __: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send(
            {
                "type": "http.response.body",
                "body": b"partial",
                "more_body": True,
            }
        )
        raise RuntimeError("sensitive streamed content")

    middleware = RequestObservabilityMiddleware(partial_failure, telemetry=telemetry)
    messages: list[Message] = []
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/stream",
        "raw_path": b"/stream",
        "root_path": "",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {},
    }

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        messages.append(message)

    with pytest.raises(RuntimeError, match="sensitive streamed content"):
        await middleware(scope, receive, send)

    spans = exporter.get_finished_spans()
    telemetry.shutdown()

    assert sum(message["type"] == "http.response.start" for message in messages) == 1
    assert len(spans) == 1
    assert spans[0].status.status_code is StatusCode.ERROR
    assert spans[0].attributes is not None
    assert spans[0].attributes["http.response.status_code"] == 200


@pytest.mark.anyio
async def test_outer_cors_middleware_decorates_generic_error_response() -> None:
    """Response middleware registered outside observability sees generated 500s."""
    settings = make_settings(otel_enabled=False)
    telemetry = create_telemetry(settings)
    application = create_app(settings, telemetry=telemetry)

    async def fail() -> None:
        raise RuntimeError("failure")

    application.add_api_route("/failure", fail, methods=["GET"])
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["https://frontend.example"],
    )
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/failure",
            headers={"origin": "https://frontend.example"},
        )

    telemetry.shutdown()

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "https://frontend.example"
