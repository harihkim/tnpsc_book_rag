"""ASGI middleware for safe request logging and server spans."""

import re
from time import perf_counter
from typing import override
from uuid import uuid4

import structlog
from opentelemetry.propagators.textmap import Getter
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tnpsc_book_rag.observability.context import correlation_context
from tnpsc_book_rag.observability.telemetry import Telemetry

_LOGGER = structlog.stdlib.get_logger(__name__)
_REQUEST_ID_HEADER = b"x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_QUIET_PATHS = frozenset({"/health/live", "/health/ready", "/metrics"})


class _HeaderGetter(Getter[dict[str, str]]):
    """Read W3C propagation values from normalized ASGI headers."""

    @override
    def get(self, carrier: dict[str, str], key: str) -> list[str] | None:
        value = carrier.get(key.lower())
        return [value] if value is not None else None

    @override
    def keys(self, carrier: dict[str, str]) -> list[str]:
        return list(carrier)


_HEADER_GETTER = _HeaderGetter()


def _headers_from_scope(scope: Scope) -> dict[str, str]:
    """Decode ASGI headers for correlation and W3C trace propagation."""
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _request_id(raw_request_id: str | None) -> str:
    """Accept a bounded safe request ID or generate a new opaque one."""
    if raw_request_id is not None and _VALID_REQUEST_ID.fullmatch(raw_request_id):
        return raw_request_id
    return uuid4().hex


def _route_template(scope: Scope) -> str:
    """Return only the matched route template, never a raw request path."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


def _finish_span(
    span: Span,
    *,
    method: str,
    route: str,
    status_code: int,
    error_type: str | None = None,
) -> None:
    """Finalize safe HTTP metadata on a server span."""
    span.update_name(f"{method} {route}")
    span.set_attribute("http.route", route)
    span.set_attribute("http.response.status_code", status_code)
    if error_type is not None:
        span.set_attribute("error.type", error_type)
    if error_type is not None or status_code >= 500:
        span.set_status(Status(StatusCode.ERROR))


class RequestObservabilityMiddleware:
    """Emit metadata-only request events and spans while suppressing probe noise."""

    def __init__(self, app: ASGIApp, *, telemetry: Telemetry) -> None:
        self._app = app
        self._telemetry = telemetry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = _headers_from_scope(scope)
        request_id = _request_id(headers.get("x-request-id"))
        method = scope.get("method", "UNKNOWN")
        quiet_request = scope.get("path") in _QUIET_PATHS

        with correlation_context(request_id=request_id):
            if quiet_request:
                await self._dispatch(
                    scope,
                    receive,
                    send,
                    request_id=request_id,
                    method=method,
                    span=None,
                    emit_success_event=False,
                )
                return

            parent_context = TraceContextTextMapPropagator().extract(
                carrier=headers,
                getter=_HEADER_GETTER,
            )
            with self._telemetry.tracer.start_as_current_span(
                f"{method} request",
                context=parent_context,
                kind=SpanKind.SERVER,
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                span.set_attribute("http.request.method", method)
                span.set_attribute("request.id", request_id)
                await self._dispatch(
                    scope,
                    receive,
                    send,
                    request_id=request_id,
                    method=method,
                    span=span,
                    emit_success_event=True,
                )

    async def _dispatch(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        request_id: str,
        method: str,
        span: Span | None,
        emit_success_event: bool,
    ) -> None:
        """Run the downstream app and safely finalize its response metadata."""
        status_code = 500
        response_started = False
        started_at = perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                response_headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != _REQUEST_ID_HEADER
                ]
                response_headers.append((_REQUEST_ID_HEADER, request_id.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self._app(scope, receive, send_with_request_id)
        except Exception as error:
            route = _route_template(scope)
            duration_ms = round((perf_counter() - started_at) * 1_000, 3)
            error_type = f"{type(error).__module__}.{type(error).__qualname__}"
            if span is not None:
                _finish_span(
                    span,
                    method=method,
                    route=route,
                    status_code=status_code,
                    error_type=error_type,
                )
            _LOGGER.error(
                "http_request_failed",
                http_method=method,
                http_route=route,
                status_code=status_code,
                duration_ms=duration_ms,
                error_code="unhandled_exception",
                error_type=error_type,
            )

            # Once headers are on the wire, replacing the response would send a
            # second response start. Record the failure and let the server abort it.
            if response_started:
                raise

            if str(scope.get("path", "")).startswith("/v1/"):
                response = JSONResponse(
                    {
                        "type": "urn:tnpsc-book-rag:problem:internal-error",
                        "title": "Internal server error",
                        "status": 500,
                        "detail": "An unexpected server error occurred.",
                        "instance": scope.get("path", "/v1"),
                        "code": "internal_error",
                        "request_id": request_id,
                        "errors": [],
                    },
                    status_code=500,
                    media_type="application/problem+json",
                )
            else:
                response = JSONResponse(
                    {
                        "detail": "Internal server error",
                        "error_code": "internal_server_error",
                        "request_id": request_id,
                    },
                    status_code=500,
                )
            await response(scope, receive, send_with_request_id)
            return

        route = _route_template(scope)
        duration_ms = round((perf_counter() - started_at) * 1_000, 3)
        if span is not None:
            _finish_span(span, method=method, route=route, status_code=status_code)
        if emit_success_event:
            _LOGGER.info(
                "http_request_completed",
                http_method=method,
                http_route=route,
                status_code=status_code,
                duration_ms=duration_ms,
            )
        elif status_code >= 500:
            _LOGGER.error(
                "http_probe_failed",
                http_method=method,
                http_route=route,
                status_code=status_code,
                duration_ms=duration_ms,
                error_code="unhealthy_probe",
            )
