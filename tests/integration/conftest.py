import socket
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
import uvicorn
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from a2a_otel_kit.adapters.mcp import ASGIApp
from a2a_otel_kit.application.settings import ObservabilitySettings
from a2a_otel_kit.entrypoints.observability import Observability


class _SignallingServer(uvicorn.Server):
    """Expose deterministic startup completion to the test thread."""

    def __init__(self, config: uvicorn.Config, started: threading.Event) -> None:
        super().__init__(config)
        self._startup_complete = started

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        self._startup_complete.set()


def _stop_server(server: uvicorn.Server, thread: threading.Thread, sock: socket.socket) -> bool:
    """Stop a loopback server and report whether its thread terminated."""
    server.should_exit = True
    thread.join(timeout=5)
    sock.close()
    return not thread.is_alive()


@contextmanager
def run_asgi_server(app: ASGIApp) -> Iterator[str]:
    """Run an ASGI app on a real loopback TCP socket for one test."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    config = uvicorn.Config(app, log_level="error", lifespan="on")
    started = threading.Event()
    server = _SignallingServer(config, started)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    if not started.wait(timeout=5) or not server.started:
        _stop_server(server, thread, sock)
        raise RuntimeError("loopback ASGI server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        body_failed = sys.exc_info()[0] is not None
        if not _stop_server(server, thread, sock) and not body_failed:
            raise RuntimeError("loopback ASGI server did not stop")


@dataclass(frozen=True, slots=True)
class TracedObservability:
    """An enabled facade paired with its in-memory exporter."""

    observability: Observability
    exporter: InMemorySpanExporter


@pytest.fixture
def traced_observability(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> Iterator[TracedObservability]:
    """Configure isolated in-memory tracing and shut it down after the test."""
    exporter = InMemorySpanExporter()
    monkeypatch.setattr("a2a_otel_kit.adapters.tracing.OTLPSpanExporter", lambda **_: exporter)
    observability = Observability.configure(
        ObservabilitySettings(
            service_name=f"{request.node.name}-integration",
            service_version="0.4.1",
            environment="test",
            enabled=True,
            otlp_endpoint="http://127.0.0.1:4318",
        )
    )
    try:
        yield TracedObservability(observability, exporter)
    finally:
        observability.shutdown()
