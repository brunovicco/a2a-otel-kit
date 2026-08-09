"""Verify end-to-end topology and privacy using the Collector receipt."""

from pathlib import Path
from typing import Any

from common import PRIVATE_CUSTOMER_ID
from receipt_utils import REQUIRED_SPANS, span_trace_id, spans_for_trace

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RECEIPT_DIR = REPO_ROOT / ".demo-receipts"
RECEIPT = RECEIPT_DIR / "traces.jsonl"
LAST_TRACE_ID = RECEIPT_DIR / "last_trace_id.txt"


def current_trace_id() -> str:
    """Read the trace ID produced by the latest successful demo execution."""
    if not LAST_TRACE_ID.exists():
        raise SystemExit(
            f"Latest trace ID not found: {LAST_TRACE_ID}\n"
            "Run `uv run python examples/end_to_end/run_demo.py` first."
        )

    trace_id = LAST_TRACE_ID.read_text(encoding="utf-8").strip()

    if not trace_id:
        raise SystemExit(f"Latest trace ID file is empty: {LAST_TRACE_ID}")

    return trace_id


def trace_payload_contains_private_value(
    spans: list[dict[str, Any]],
    private_value: str,
) -> bool:
    """Check only the current trace representation for private business content."""
    return private_value in repr(spans)


def main() -> None:
    """Require topology, shared trace identity, and metadata-only telemetry."""
    trace_id = current_trace_id()

    if not RECEIPT.exists():
        raise SystemExit(f"Collector receipt not found: {RECEIPT}")

    trace_spans = spans_for_trace(RECEIPT, trace_id)

    if not trace_spans:
        raise SystemExit(f"No spans found for latest trace_id={trace_id} in {RECEIPT}")

    print(f"Verifying trace: {trace_id}")
    print()

    ok = True
    required_matches: list[dict[str, Any]] = []

    for label, expected_name in REQUIRED_SPANS.items():
        found = [span for span in trace_spans if span.get("name") == expected_name]

        if found:
            required_matches.extend(found)
            print(
                f"✓ {label} span found: {expected_name} "
                f"({len(found)} span{'s' if len(found) != 1 else ''})"
            )
        else:
            print(f"✗ {label} span missing: {expected_name}")
            ok = False

    required_trace_ids = {
        span_trace_id(span) for span in required_matches if span_trace_id(span) is not None
    }

    if required_trace_ids == {trace_id}:
        print(f"✓ Required spans share one trace_id: {trace_id}")
    else:
        print(
            "✗ Required spans do not resolve to the expected trace_id: "
            f"{sorted(value for value in required_trace_ids if value is not None)}"
        )
        ok = False

    if trace_payload_contains_private_value(
        trace_spans,
        PRIVATE_CUSTOMER_ID,
    ):
        print("✗ Private business identifier leaked into current trace telemetry")
        ok = False
    else:
        print("✓ Private business identifier absent from current trace telemetry")

    print()
    print("Observed span names for this trace:")

    counts: dict[str, int] = {}
    for span in trace_spans:
        name = str(span.get("name"))
        counts[name] = counts.get(name, 0) + 1

    for name in sorted(counts):
        print(f"  - {name} ({counts[name]})")

    print()

    if not ok:
        raise SystemExit("Demo verification: FAILED")

    print("Demo verification: PASSED")


if __name__ == "__main__":
    main()
