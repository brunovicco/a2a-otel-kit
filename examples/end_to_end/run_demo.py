"""Run the end-to-end A2A → MCP observability demo deterministically."""

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from receipt_utils import REQUIRED_SPANS, wait_for_required_spans

DEMO_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEMO_DIR.parent.parent
RECEIPT_DIR = REPO_ROOT / ".demo-receipts"
RECEIPT = RECEIPT_DIR / "traces.jsonl"
LAST_TRACE_ID = RECEIPT_DIR / "last_trace_id.txt"

DemoScript = Literal["customer_data_mcp.py", "risk_agent.py"]


def wait_for_tcp(
    host: str,
    port: int,
    timeout_seconds: float = 20.0,
) -> None:
    """Wait for a TCP listener without generating application requests or traces."""
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.25)

    raise RuntimeError(f"Timed out waiting for {host}:{port}")


def start(script: DemoScript) -> subprocess.Popen[str]:
    """Start one demo service using the active Python interpreter."""
    # Both the interpreter and script are constrained to trusted local values.
    return subprocess.Popen(  # noqa: S603
        [sys.executable, str(DEMO_DIR / script)],
        cwd=str(DEMO_DIR),
        text=True,
        env=os.environ.copy(),
    )


def stop(process: subprocess.Popen[str]) -> None:
    """Gracefully stop a child process, falling back to kill only on timeout."""
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)

    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


async def main() -> None:
    """Execute one request and require positive receipt before child shutdown."""
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)

    # Never truncate traces.jsonl while the Collector is running. The file exporter
    # may already hold an open descriptor with its own write offset. Historical
    # records are safe because both runner and verifier filter by last_trace_id.
    LAST_TRACE_ID.unlink(missing_ok=True)

    print("a2a-otel-kit end-to-end demo")
    print("=" * 40)

    mcp = start("customer_data_mcp.py")
    risk = start("risk_agent.py")

    try:
        # TCP readiness does not create fake MCP/A2A requests or spans.
        wait_for_tcp("127.0.0.1", 8102)
        print("✓ Customer Data MCP ready")

        wait_for_tcp("127.0.0.1", 8101)
        print("✓ Risk Agent ready")

        from orchestrator import run

        print("\nRunning traced request...\n")
        trace_id = await run()
        LAST_TRACE_ID.write_text(trace_id + "\n", encoding="utf-8")

        print("\nTelemetry")
        print("-" * 40)
        print(f"Trace ID: {trace_id}")
        print("✓ A2A request completed")
        print("✓ MCP request completed")
        print("Waiting for positive Collector receipt...")

        # Critical ordering:
        # 1. Keep Risk Agent and MCP alive.
        # 2. Let their BatchSpanProcessors export naturally.
        # 3. Require all protocol spans in the Collector receipt.
        # 4. Only then terminate the child services.
        spans = wait_for_required_spans(
            RECEIPT,
            trace_id,
            timeout_seconds=20.0,
        )

        names = [str(span.get("name")) for span in spans]
        print("✓ Required A2A/MCP spans received by OpenTelemetry Collector")

        for label, expected_name in REQUIRED_SPANS.items():
            count = names.count(expected_name)
            print(f"  ✓ {label}: {expected_name} ({count} span{'s' if count != 1 else ''})")

        print("\nDemo execution: PASSED")
        print("\nNext:")
        print("  uv run python examples/end_to_end/verify_trace.py")
        print("  Open http://localhost:3000 and inspect this trace in Tempo.")
    finally:
        stop(risk)
        stop(mcp)


if __name__ == "__main__":
    asyncio.run(main())
