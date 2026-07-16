"""Tests for the Observability facade: lifecycle, tracing, and structured event emission.

The "enabled" path patches the concrete ``OTLPSpanExporter`` used inside
``a2a_otel_kit.adapters.tracing`` for an in-memory fake, so these tests exercise the real SDK
TracerProvider/BatchSpanProcessor wiring without ever attempting a network call.
"""

import json
from collections.abc import Sequence

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from a2a_otel_kit.application.settings import ObservabilitySettings
from a2a_otel_kit.entrypoints.observability import Observability


class _FakeSpanExporter(SpanExporter):
    """In-memory stand-in for the OTLP HTTP exporter; never touches the network."""

    def __init__(self, **_: object) -> None:
        self.exported: list[ReadableSpan] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Record spans in memory instead of sending them anywhere."""
        self.exported.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """Nothing to release for an in-memory exporter."""

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Always succeed immediately; there is no background export to wait for."""
        return True


def _disabled_settings(**overrides: object) -> ObservabilitySettings:
    defaults: dict[str, object] = {
        "service_name": "billing",
        "service_version": "1.0.0",
        "environment": "test",
    }
    defaults.update(overrides)
    return ObservabilitySettings(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def enabled_settings(monkeypatch: pytest.MonkeyPatch) -> ObservabilitySettings:
    """Settings with tracing enabled, with the OTLP exporter patched to an in-memory fake."""
    monkeypatch.setattr("a2a_otel_kit.adapters.tracing.OTLPSpanExporter", _FakeSpanExporter)
    return _disabled_settings(enabled=True, otlp_endpoint="http://localhost:4318")


def test_disabled_observability_produces_a_non_recording_span() -> None:
    """Disabled mode is a true no-op: no exporter configuration is required."""
    obs = Observability.configure(_disabled_settings())

    with obs.start_span("op") as span:
        assert span.is_recording() is False

    obs.shutdown()


def test_valid_initialization_produces_a_recording_span(
    enabled_settings: ObservabilitySettings,
) -> None:
    """Enabling tracing with a valid endpoint builds a real, recording tracer."""
    obs = Observability.configure(enabled_settings)

    with obs.start_span("op") as span:
        assert span.is_recording() is True
        assert span.get_span_context().is_valid

    obs.shutdown()


def test_repeated_initialization_does_not_raise() -> None:
    """Configuring twice builds two independent instances without error."""
    settings = _disabled_settings()

    first = Observability.configure(settings)
    second = Observability.configure(settings)

    assert first is not second
    first.shutdown()
    second.shutdown()


def test_repeated_shutdown_is_safe(enabled_settings: ObservabilitySettings) -> None:
    """Shutting down an already-shut-down instance is a no-op, not an error."""
    obs = Observability.configure(enabled_settings)

    obs.shutdown()
    obs.shutdown()


def test_flush_returns_true_immediately_when_disabled() -> None:
    """Flushing a disabled instance succeeds trivially: there is nothing to export."""
    obs = Observability.configure(_disabled_settings())

    assert obs.flush() is True

    obs.shutdown()


def test_flush_succeeds_when_enabled(enabled_settings: ObservabilitySettings) -> None:
    """Flushing an enabled instance with the fake exporter succeeds."""
    obs = Observability.configure(enabled_settings)

    assert obs.flush(timeout_seconds=1.0) is True

    obs.shutdown()


def test_emit_event_writes_a_versioned_structured_json_event(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """emit_event() writes one JSON line carrying event_name, event_outcome, schema_version."""
    obs = Observability.configure(_disabled_settings())

    obs.emit_event("workflow.started", "success", operation="review")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["event"] == "workflow.started"
    assert payload["event_outcome"] == "success"
    assert payload["schema_version"] == 1
    assert payload["operation"] == "review"

    obs.shutdown()


def test_emit_event_drops_sensitive_and_unallowlisted_attributes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Attributes passed to emit_event go through the same allowlist/redaction as spans."""
    obs = Observability.configure(_disabled_settings())

    obs.emit_event(
        "workflow.started",
        "success",
        password="must-not-leave-process",  # noqa: S106 -- deliberate test value, not a real secret
        unallowlisted_field="also dropped",
        operation="review",
    )

    payload = json.loads(capsys.readouterr().out.strip())
    assert "password" not in payload
    assert "unallowlisted_field" not in payload
    assert payload["operation"] == "review"

    obs.shutdown()


def test_emit_event_includes_trace_and_span_id_when_a_span_is_active(
    capsys: pytest.CaptureFixture[str],
    enabled_settings: ObservabilitySettings,
) -> None:
    """trace_id/span_id are injected automatically only while a valid span is active."""
    obs = Observability.configure(enabled_settings)

    with obs.start_span("op") as span:
        obs.emit_event("step.completed", "success")
        expected_trace_id = format(span.get_span_context().trace_id, "032x")
        expected_span_id = format(span.get_span_context().span_id, "016x")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["trace_id"] == expected_trace_id
    assert payload["span_id"] == expected_span_id

    obs.shutdown()


def test_emit_event_omits_trace_context_when_no_span_is_active(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No active span means no trace_id/span_id are fabricated."""
    obs = Observability.configure(_disabled_settings())

    obs.emit_event("step.completed", "success")

    payload = json.loads(capsys.readouterr().out.strip())
    assert "trace_id" not in payload
    assert "span_id" not in payload

    obs.shutdown()
