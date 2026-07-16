"""OpenTelemetry tracer-provider adapter: vendor-neutral OTLP export only.

Builds either a no-op tracer provider (observability disabled) or a real SDK tracer provider that
batches spans to an OTLP/HTTP endpoint - typically a local OTel Collector, which owns any further
fan-out to vendor backends. This module never imports a vendor SDK (Datadog, Langfuse, ...).
"""

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import NoOpTracerProvider, TracerProvider

from a2a_otel_kit.application.ports import TracerLifecycle
from a2a_otel_kit.application.settings import ObservabilitySettings

# OTel resource semantic convention keys (stable, hardcoded rather than depending on the
# still-pre-1.0 opentelemetry-semantic-conventions package for three constant strings).
_SERVICE_NAME_KEY = "service.name"
_SERVICE_VERSION_KEY = "service.version"
_DEPLOYMENT_ENVIRONMENT_KEY = "deployment.environment"


def build_tracer_provider(
    settings: ObservabilitySettings,
) -> tuple[TracerProvider, TracerLifecycle | None]:
    """Build a tracer provider and its lifecycle handle from validated settings.

    Returns ``(NoOpTracerProvider(), None)`` when ``settings.enabled`` is ``False``: spans created
    from the returned provider are not recorded and cost nothing. Returns a configured SDK
    ``TracerProvider`` batching to an OTLP/HTTP exporter otherwise; the same instance is returned
    as both the provider and its lifecycle handle, since the SDK provider already implements
    :class:`~a2a_otel_kit.application.ports.TracerLifecycle` (``force_flush``/``shutdown``).
    """
    if not settings.enabled:
        return NoOpTracerProvider(), None

    resource = Resource.create(
        {
            _SERVICE_NAME_KEY: settings.service_name,
            _SERVICE_VERSION_KEY: settings.service_version,
            _DEPLOYMENT_ENVIRONMENT_KEY: settings.environment,
        }
    )
    provider = SDKTracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=settings.otlp_endpoint,
        timeout=settings.otlp_timeout_seconds,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider, provider
