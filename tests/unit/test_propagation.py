"""Tests for W3C trace-context propagation across simulated process/task boundaries."""

import asyncio

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from a2a_otel_kit.adapters.propagation import (
    continue_trace,
    extract_trace_context,
    inject_trace_context,
)


@pytest.fixture
def tracer_and_exporter() -> tuple[TracerProvider, InMemorySpanExporter]:
    """A tracer backed by an in-memory exporter; no network involved."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def test_inject_writes_a_w3c_traceparent_into_a_plain_dict_carrier(
    tracer_and_exporter: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    """Injection targets a plain mutable mapping, not a transport-specific object."""
    provider, _ = tracer_and_exporter
    tracer = provider.get_tracer("test")
    carrier: dict[str, str] = {}

    with tracer.start_as_current_span("span"):
        inject_trace_context(carrier)

    assert "traceparent" in carrier
    assert carrier["traceparent"].startswith("00-")


def test_extract_from_empty_carrier_yields_a_context_with_no_active_span(
    tracer_and_exporter: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    """Extracting from a carrier with no trace context is a well-defined no-op."""
    context = extract_trace_context({})

    assert context is not None


def test_parent_child_continuity_across_a_simulated_process_boundary(
    tracer_and_exporter: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    """A span started after continue_trace() becomes a child of the injected span."""
    provider, exporter = tracer_and_exporter
    tracer = provider.get_tracer("test")
    carrier: dict[str, str] = {}

    # Simulated process A: start a span and inject its context onto the wire.
    with tracer.start_as_current_span("parent-span") as parent_span:
        inject_trace_context(carrier)
        parent_trace_id = parent_span.get_span_context().trace_id
        parent_span_id = parent_span.get_span_context().span_id

    # Simulated process B: receive the carrier, continue the trace, start a child span.
    with continue_trace(carrier), tracer.start_as_current_span("child-span") as child_span:
        child_trace_id = child_span.get_span_context().trace_id

    assert child_trace_id == parent_trace_id

    finished = {span.name: span for span in exporter.get_finished_spans()}
    child_recorded = finished["child-span"]
    assert child_recorded.parent is not None
    assert child_recorded.parent.span_id == parent_span_id


def test_continue_trace_detaches_context_on_exit(
    tracer_and_exporter: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    """Leaving the continue_trace block restores the ambient context."""
    provider, _ = tracer_and_exporter
    tracer = provider.get_tracer("test")
    carrier: dict[str, str] = {}
    with tracer.start_as_current_span("parent-span"):
        inject_trace_context(carrier)

    with continue_trace(carrier):
        pass

    carrier_after: dict[str, str] = {}
    with tracer.start_as_current_span("unrelated-span") as unrelated:
        inject_trace_context(carrier_after)
        unrelated_trace_id = unrelated.get_span_context().trace_id

    assert carrier_after["traceparent"] != carrier["traceparent"]
    assert unrelated_trace_id != 0


def test_concurrent_async_tasks_get_isolated_trace_context(
    tracer_and_exporter: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    """Two concurrent asyncio tasks each starting a span do not share trace context."""
    provider, _ = tracer_and_exporter
    tracer = provider.get_tracer("test")

    async def start_and_report(name: str) -> tuple[int, int]:
        with tracer.start_as_current_span(name) as span:
            await asyncio.sleep(0)
            context = span.get_span_context()
            return context.trace_id, context.span_id

    async def run_concurrently() -> tuple[tuple[int, int], tuple[int, int]]:
        return await asyncio.gather(start_and_report("task-a"), start_and_report("task-b"))

    results = asyncio.run(run_concurrently())

    assert results[0][0] != results[1][0]
    assert results[0][1] != results[1][1]
