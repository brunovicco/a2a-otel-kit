"""Utilities for reading and waiting on OpenTelemetry Collector demo receipts."""

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REQUIRED_SPANS = {
    "A2A client": "a2a.client.get_task",
    "A2A server": "a2a.server.on_get_task",
    "MCP client": "mcp.client.streamable_http",
    "MCP server": "mcp.server.streamable_http",
}


def walk(value: Any) -> Iterator[Any]:
    """Yield every nested item in a JSON-compatible value."""
    yield value

    if isinstance(value, dict):
        for nested in value.values():
            yield from walk(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk(nested)


def span_trace_id(span: dict[str, Any]) -> str | None:
    """Read the trace ID from common Collector JSON field spellings."""
    value = span.get("traceId", span.get("trace_id"))
    return str(value) if value is not None else None


def load_spans(receipt: Path) -> list[dict[str, Any]]:
    """Extract span-like dictionaries from a Collector JSONL file receipt."""
    if not receipt.exists():
        return []

    spans: list[dict[str, Any]] = []

    for line in receipt.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        if not line.strip():
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue

        for item in walk(payload):
            if (
                isinstance(item, dict)
                and "name" in item
                and ("traceId" in item or "trace_id" in item)
            ):
                spans.append(item)

    return spans


def spans_for_trace(
    receipt: Path,
    trace_id: str,
) -> list[dict[str, Any]]:
    """Return spans belonging only to one distributed trace."""
    return [span for span in load_spans(receipt) if span_trace_id(span) == trace_id]


def observed_names(
    receipt: Path,
    trace_id: str,
) -> set[str]:
    """Return unique span names observed for a trace."""
    return {
        str(span["name"])
        for span in spans_for_trace(receipt, trace_id)
        if span.get("name") is not None
    }


def missing_required_span_names(
    receipt: Path,
    trace_id: str,
) -> set[str]:
    """Return required demo span names not yet exported for the trace."""
    names = observed_names(receipt, trace_id)
    return {
        expected_name for expected_name in REQUIRED_SPANS.values() if expected_name not in names
    }


def wait_for_required_spans(
    receipt: Path,
    trace_id: str,
    timeout_seconds: float = 20.0,
    poll_interval_seconds: float = 0.25,
) -> list[dict[str, Any]]:
    """Wait until all required A2A/MCP spans are positively received."""
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        missing = missing_required_span_names(receipt, trace_id)
        if not missing:
            return spans_for_trace(receipt, trace_id)

        time.sleep(poll_interval_seconds)

    names = sorted(observed_names(receipt, trace_id))
    missing = sorted(missing_required_span_names(receipt, trace_id))

    raise RuntimeError(
        "Timed out waiting for required spans in Collector receipt. "
        f"trace_id={trace_id}; missing={missing}; observed={names}"
    )
