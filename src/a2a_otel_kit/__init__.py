"""a2a-otel-kit: a reusable OpenTelemetry, propagation, and structured-logging foundation.

Vendor-neutral by design: this library emits standard OTLP and never imports a vendor SDK
(Datadog, Langfuse, ...). See ``README.md`` for scope, configuration, and deferred integrations.

Importing this package performs no I/O and configures no global telemetry; every capability below
is explicit and must be invoked by the caller.
"""

from a2a_otel_kit.adapters.propagation import (
    continue_trace,
    extract_trace_context,
    inject_trace_context,
)
from a2a_otel_kit.application.ports import OTLPHeadersProvider
from a2a_otel_kit.application.settings import ObservabilitySettings
from a2a_otel_kit.domain.attributes import (
    AttributeValue,
    StructuredEvent,
    StructuredEventOutcome,
    sanitize_attributes,
)
from a2a_otel_kit.domain.errors import (
    InvalidObservabilityConfigurationError,
    InvalidStructuredEventError,
    ObservabilityError,
)
from a2a_otel_kit.entrypoints.observability import Observability

__all__ = [
    "AttributeValue",
    "InvalidObservabilityConfigurationError",
    "InvalidStructuredEventError",
    "OTLPHeadersProvider",
    "Observability",
    "ObservabilityError",
    "ObservabilitySettings",
    "StructuredEvent",
    "StructuredEventOutcome",
    "continue_trace",
    "extract_trace_context",
    "inject_trace_context",
    "sanitize_attributes",
]
