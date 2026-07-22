"""OpenTelemetry tracing configured without content capture."""

from dataclasses import dataclass

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import NoOpTracerProvider, Tracer

from tnpsc_book_rag.config import Settings

_INSTRUMENTATION_NAME = "tnpsc_book_rag"


@dataclass(frozen=True, slots=True)
class Telemetry:
    """Application-owned tracer and its optional SDK lifecycle."""

    tracer: Tracer
    provider: TracerProvider | None = None

    def shutdown(self) -> None:
        """Flush and stop configured span processors."""
        if self.provider is not None:
            self.provider.shutdown()


def create_telemetry(
    settings: Settings,
    *,
    span_exporter: SpanExporter | None = None,
) -> Telemetry:
    """Create tracing with safe resource metadata and no captured content."""
    if not settings.otel_enabled:
        tracer = NoOpTracerProvider().get_tracer(_INSTRUMENTATION_NAME)
        return Telemetry(tracer=tracer)

    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "deployment.environment.name": settings.environment.value,
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings.otel_sample_ratio)),
        shutdown_on_exit=False,
    )

    if span_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    elif settings.otel_traces_endpoint is not None:
        exporter = OTLPSpanExporter(endpoint=str(settings.otel_traces_endpoint))
        provider.add_span_processor(BatchSpanProcessor(exporter))

    return Telemetry(
        tracer=provider.get_tracer(_INSTRUMENTATION_NAME),
        provider=provider,
    )
