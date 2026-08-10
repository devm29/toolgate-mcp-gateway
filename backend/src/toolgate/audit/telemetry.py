from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SpanExporter

from toolgate import __version__
from toolgate.config import OtelExporter, Settings

TRACER_NAME = "toolgate.gateway"


def build_tracer_provider(settings: Settings) -> TracerProvider:
    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: settings.otel_service_name, "service.version": __version__})
    )
    exporter: SpanExporter | None = None
    if settings.otel_exporter is OtelExporter.CONSOLE:
        exporter = ConsoleSpanExporter()
    elif settings.otel_exporter is OtelExporter.OTLP:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint) if settings.otel_endpoint else OTLPSpanExporter()
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def install_global(provider: TracerProvider) -> None:
    # The MCP SDK emits its own per-message SERVER spans from the global provider; sharing it makes
    # our execute_tool spans children of those.
    trace.set_tracer_provider(provider)
