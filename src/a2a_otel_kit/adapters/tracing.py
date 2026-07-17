"""OpenTelemetry tracer-provider adapter: vendor-neutral OTLP export only.

Builds either a no-op tracer provider (observability disabled) or a real SDK tracer provider that
batches spans to an OTLP/HTTP endpoint - typically a local OTel Collector, which owns any further
fan-out to vendor backends. This module never imports a vendor SDK (Datadog, Langfuse, ...).
"""

import re
from collections.abc import Mapping

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import NoOpTracerProvider, TracerProvider

from a2a_otel_kit.application.ports import OTLPHeadersProvider, TracerLifecycle
from a2a_otel_kit.application.settings import ObservabilitySettings
from a2a_otel_kit.domain.errors import InvalidObservabilityConfigurationError

# OTel resource semantic convention keys (stable, hardcoded rather than depending on the
# still-pre-1.0 opentelemetry-semantic-conventions package for three constant strings).
_SERVICE_NAME_KEY = "service.name"
_SERVICE_VERSION_KEY = "service.version"
_DEPLOYMENT_ENVIRONMENT_KEY = "deployment.environment"
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_MAX_HEADER_COUNT = 32
_MAX_HEADER_NAME_LENGTH = 256
_MAX_HEADER_VALUE_LENGTH = 8192
_MAX_HEADERS_TOTAL_LENGTH = 32768


def build_tracer_provider(
    settings: ObservabilitySettings,
    *,
    otlp_headers_provider: OTLPHeadersProvider | None = None,
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

    headers = _resolve_otlp_headers(otlp_headers_provider)

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
        headers=headers,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider, provider


def _resolve_otlp_headers(provider: OTLPHeadersProvider | None) -> dict[str, str] | None:
    """Resolve and validate caller-owned credentials without rendering secret material."""
    if provider is None:
        return None
    try:
        supplied = provider()
    except Exception:
        raise InvalidObservabilityConfigurationError(
            "OTLP headers provider failed during observability setup"
        ) from None

    headers: dict[str, str] = {}
    if not isinstance(supplied, Mapping):
        raise InvalidObservabilityConfigurationError(
            "OTLP headers provider must return a string mapping"
        )
    try:
        items = list(supplied.items())
    except Exception:
        raise InvalidObservabilityConfigurationError(
            "OTLP headers provider result could not be read"
        ) from None
    if len(items) > _MAX_HEADER_COUNT:
        raise InvalidObservabilityConfigurationError(
            "OTLP headers provider returned too many headers"
        )
    total_length = 0
    for name, value in items:
        if not isinstance(name, str) or not isinstance(value, str):
            raise InvalidObservabilityConfigurationError(
                "OTLP headers provider must return a string mapping"
            )
        if len(name) > _MAX_HEADER_NAME_LENGTH or _HEADER_NAME.fullmatch(name) is None:
            raise InvalidObservabilityConfigurationError(
                "OTLP headers provider returned an invalid header name"
            )
        if "\r" in value or "\n" in value:
            raise InvalidObservabilityConfigurationError(
                "OTLP headers provider returned an invalid header value"
            )
        if len(value) > _MAX_HEADER_VALUE_LENGTH:
            raise InvalidObservabilityConfigurationError(
                "OTLP headers provider returned an oversized header value"
            )
        total_length += len(name) + len(value)
        if total_length > _MAX_HEADERS_TOTAL_LENGTH:
            raise InvalidObservabilityConfigurationError(
                "OTLP headers provider returned oversized headers"
            )
        headers[name] = value
    return headers
