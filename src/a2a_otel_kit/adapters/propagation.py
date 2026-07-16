"""Protocol-neutral W3C trace-context propagation.

Carriers are plain ``Mapping``/``MutableMapping[str, str]`` - the same shape as HTTP headers, gRPC
metadata, or message-queue headers - so a future A2A or MCP transport adapter can reuse these
helpers without this library depending on that transport.

Uses a single, stateless ``TraceContextTextMapPropagator`` instance directly rather than
OpenTelemetry's global propagator registry (``opentelemetry.propagate.set_global_textmap``): this
keeps injection and extraction free of global mutable state, so nothing here "configures global
telemetry" as a side effect of import or use.
"""

from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager

from opentelemetry import context as otel_context
from opentelemetry.context import Context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_PROPAGATOR = TraceContextTextMapPropagator()


def inject_trace_context(carrier: MutableMapping[str, str]) -> None:
    """Write the current W3C ``traceparent``/``tracestate`` into a mutable text carrier."""
    _PROPAGATOR.inject(carrier)


def extract_trace_context(carrier: Mapping[str, str]) -> Context:
    """Read a W3C ``traceparent``/``tracestate`` from a mapping-like carrier.

    Returns a new :class:`~opentelemetry.context.Context`; it does not become current until
    attached, typically via :func:`continue_trace`.
    """
    return _PROPAGATOR.extract(carrier)


@contextmanager
def continue_trace(carrier: Mapping[str, str]) -> Iterator[None]:
    """Make an extracted trace context current for the duration of the block.

    Any span started inside this block becomes a child of the span described by ``carrier``,
    simulating continuation of a trace across a process boundary (a future A2A task hand-off, an
    MCP call, a queue message).
    """
    extracted = extract_trace_context(carrier)
    token = otel_context.attach(extracted)
    try:
        yield
    finally:
        otel_context.detach(token)
