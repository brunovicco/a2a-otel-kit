"""Composition root: the ``Observability`` facade.

The only place in this library that wires domain sanitization, application settings/ports, and
the OpenTelemetry/structlog adapters together. Callers use this facade instead of constructing
tracer providers or exporters directly.
"""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Self

import structlog
from opentelemetry.trace import Span, SpanKind, Tracer

from a2a_otel_kit.adapters.tracing import build_tracer_provider
from a2a_otel_kit.application.ports import OTLPHeadersProvider, TracerLifecycle
from a2a_otel_kit.application.settings import ObservabilitySettings
from a2a_otel_kit.domain.attributes import (
    AttributeValue,
    StructuredEvent,
    StructuredEventOutcome,
    sanitize_attributes,
)
from a2a_otel_kit.entrypoints.logging import configure_logging

DEFAULT_TIMEOUT_SECONDS = 5.0


class Observability:
    """Explicit lifecycle and telemetry facade for one process.

    Construct via :meth:`configure`, not directly. Each call to :meth:`configure` builds an
    independent instance with no shared global OpenTelemetry state - repeated initialization never
    raises and never corrupts a previously configured instance's state. When replacing an active
    instance, call :meth:`shutdown` on the old one first to release its exporter resources.
    """

    def __init__(
        self,
        *,
        settings: ObservabilitySettings,
        tracer: Tracer,
        lifecycle: TracerLifecycle | None,
    ) -> None:
        """Wrap an already-built tracer and lifecycle handle; prefer :meth:`configure`."""
        self._settings = settings
        self._tracer = tracer
        self._lifecycle = lifecycle
        self._logger = structlog.get_logger(settings.service_name)
        self._is_shut_down = False

    @classmethod
    def configure(
        cls,
        settings: ObservabilitySettings,
        *,
        otlp_headers_provider: OTLPHeadersProvider | None = None,
    ) -> Self:
        """Initialize logging and tracing, resolving optional OTLP headers exactly once."""
        configure_logging(
            service=settings.service_name,
            environment=settings.environment,
            version=settings.service_version,
            log_level=settings.log_level,
            log_format=settings.log_format,
        )
        provider, lifecycle = build_tracer_provider(
            settings, otlp_headers_provider=otlp_headers_provider
        )
        tracer = provider.get_tracer(settings.service_name, settings.service_version)
        return cls(settings=settings, tracer=tracer, lifecycle=lifecycle)

    @property
    def settings(self) -> ObservabilitySettings:
        """Return the settings this instance was configured with."""
        return self._settings

    def start_span(
        self,
        name: str,
        *,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Mapping[str, object] | None = None,
        record_exception: bool = True,
    ) -> AbstractContextManager[Span]:
        """Start a span as the current span for the duration of a ``with`` block.

        Produces a no-op, non-recording span when observability is disabled, so callers never
        need to branch on whether tracing is enabled. Attributes are sanitized through the same
        allowlist as :meth:`emit_event`; span attributes cannot carry ``None``, so a sanitized
        ``None`` value is dropped rather than sent as an empty attribute.

        ``record_exception`` defaults to OpenTelemetry's own default (``True``): the span
        automatically captures the exception's type, message, and stack trace as a span event,
        and sets an ERROR status with that message as its description. Pass ``False`` when
        wrapping a boundary whose exceptions may carry content this library must not record
        verbatim (for example, a remote peer's error message) - the caller remains responsible
        for setting a safe status explicitly in that case.
        """
        span_attributes = {
            key: value
            for key, value in sanitize_attributes(attributes).items()
            if value is not None
        }
        return self._tracer.start_as_current_span(
            name,
            kind=kind,
            attributes=span_attributes,
            record_exception=record_exception,
            set_status_on_exception=record_exception,
        )

    def emit_event(
        self,
        event_name: str,
        event_outcome: StructuredEventOutcome | str,
        **attributes: AttributeValue,
    ) -> None:
        """Emit one versioned structured-log event, allowlisting its attributes.

        Adds ``trace_id``/``span_id`` automatically when called inside an active span, via the
        logging processor installed by :func:`~a2a_otel_kit.entrypoints.logging.configure_logging`.
        """
        outcome = StructuredEventOutcome(event_outcome)
        event = StructuredEvent(event_name=event_name, event_outcome=outcome, attributes=attributes)
        clean_attributes = sanitize_attributes(event.attributes)
        self._logger.info(
            event.event_name,
            schema_version=event.schema_version,
            event_outcome=event.event_outcome.value,
            **clean_attributes,
        )

    def flush(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> bool:
        """Block until pending spans are exported; returns ``True`` immediately when disabled."""
        if self._lifecycle is None:
            return True
        return self._lifecycle.force_flush(timeout_millis=int(timeout_seconds * 1000))

    def shutdown(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        """Flush and release exporter resources. Safe to call more than once."""
        if self._is_shut_down:
            return
        if self._lifecycle is not None:
            self.flush(timeout_seconds)
            self._lifecycle.shutdown()
        self._is_shut_down = True
