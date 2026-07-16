"""Application-owned ports, defined near the use case that consumes them.

Adapters satisfy these Protocols structurally; no inheritance is required. The OpenTelemetry SDK's
own ``TracerProvider`` already implements :class:`TracerLifecycle` without any wrapper code.
"""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Protocol

from opentelemetry.trace import Span, SpanKind

from a2a_otel_kit.domain.attributes import AttributeValue, StructuredEventOutcome


class TracerLifecycle(Protocol):
    """Flush and shutdown behavior for an installed tracer backend.

    Absent (``None``) when observability is disabled, since there is nothing to flush or shut
    down for a no-op tracer provider.
    """

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Block until pending spans are exported or ``timeout_millis`` elapses."""
        ...

    def shutdown(self) -> None:
        """Release exporter resources. Safe to call at most once per backend instance."""
        ...


class ObservabilityFacade(Protocol):
    """The subset of Observability that a protocol adapter depends on.

    ``Observability`` here refers to
    :class:`~a2a_otel_kit.entrypoints.observability.Observability`; a protocol-specific
    integration adapter (e.g. the optional A2A SDK adapter) depends on this narrow contract
    instead of importing the entrypoints-layer facade directly, preserving the documented
    dependency direction (adapters -> application/domain, not adapters -> entrypoints). The
    concrete ``Observability`` class satisfies this Protocol structurally.
    """

    def start_span(
        self,
        name: str,
        *,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Mapping[str, object] | None = None,
        record_exception: bool = True,
    ) -> AbstractContextManager[Span]:
        """Start a span as the current span for the duration of a ``with`` block."""
        ...

    def emit_event(
        self,
        event_name: str,
        event_outcome: StructuredEventOutcome | str,
        **attributes: AttributeValue,
    ) -> None:
        """Emit one versioned structured-log event, allowlisting its attributes."""
        ...
