"""Tests for the structured logging bootstrap and active-span correlation."""

import json
import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from a2a_otel_kit.entrypoints.logging import (
    bind_correlation_id,
    clear_request_context,
    configure_logging,
)


def test_configure_logging_emits_json_with_service_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A configured logger writes one JSON line with the bound service fields."""
    configure_logging(service="billing", environment="test", version="1.2.3", log_level="INFO")

    logging.getLogger(__name__).info("order_created")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["service"] == "billing"
    assert payload["environment"] == "test"
    assert payload["version"] == "1.2.3"
    assert payload["event"] == "order_created"


def test_configure_logging_respects_log_level(capsys: pytest.CaptureFixture[str]) -> None:
    """A DEBUG record is dropped when log_level is INFO."""
    configure_logging(service="billing", environment="test", version="1.2.3", log_level="INFO")

    logging.getLogger(__name__).debug("noisy_detail")

    assert capsys.readouterr().out.strip() == ""


def test_configure_logging_supports_console_format(capsys: pytest.CaptureFixture[str]) -> None:
    """log_format='console' renders a human-readable line instead of JSON."""
    configure_logging(service="billing", environment="test", version="1.2.3", log_format="console")

    logging.getLogger(__name__).info("order_created")

    output = capsys.readouterr().out
    with pytest.raises(json.JSONDecodeError):
        json.loads(output.strip())
    assert "order_created" in output


def test_clear_request_context_keeps_process_wide_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Clearing per-request context drops the correlation id but keeps service fields."""
    configure_logging(service="billing", environment="test", version="1.2.3")
    bind_correlation_id("req-1")

    clear_request_context()
    logging.getLogger(__name__).info("after_clear")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["service"] == "billing"
    assert "correlation_id" not in payload


def test_bind_correlation_id_appears_on_subsequent_log_events(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bound correlation id is attached to every subsequent event until cleared."""
    configure_logging(service="billing", environment="test", version="1.2.3")
    bind_correlation_id("req-42")

    logging.getLogger(__name__).info("step_completed")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["correlation_id"] == "req-42"


def test_log_event_includes_trace_and_span_id_when_a_span_is_active(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """trace_id/span_id are injected from the real active OpenTelemetry span, not bound manually."""
    configure_logging(service="billing", environment="test", version="1.2.3")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("op") as span:
        logging.getLogger(__name__).info("inside_span")
        expected_trace_id = format(span.get_span_context().trace_id, "032x")
        expected_span_id = format(span.get_span_context().span_id, "016x")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["trace_id"] == expected_trace_id
    assert payload["span_id"] == expected_span_id


def test_log_event_omits_trace_context_when_no_span_is_active(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No active span means no fabricated trace_id/span_id are attached."""
    configure_logging(service="billing", environment="test", version="1.2.3")

    logging.getLogger(__name__).info("no_span")

    payload = json.loads(capsys.readouterr().out.strip())
    assert "trace_id" not in payload
    assert "span_id" not in payload
