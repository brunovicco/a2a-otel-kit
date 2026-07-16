import asyncio
import json
import subprocess
import sys

import httpx
import pytest
from opentelemetry import context as otel_context
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    SpanKind,
    TraceFlags,
    TraceState,
    get_current_span,
    set_span_in_context,
)

from a2a_otel_kit.adapters.mcp import (
    ASGIMessage,
    Receive,
    Scope,
    Send,
    TracingASGIMiddleware,
    TracingAsyncTransport,
)
from a2a_otel_kit.application.settings import ObservabilitySettings
from a2a_otel_kit.entrypoints.observability import Observability


def _observability(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Observability, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    monkeypatch.setattr("a2a_otel_kit.adapters.tracing.OTLPSpanExporter", lambda **_: exporter)
    settings = ObservabilitySettings(
        service_name="mcp-test",
        service_version="0.3.0",
        environment="test",
        enabled=True,
        otlp_endpoint="http://localhost:4318",
    )
    return Observability.configure(settings), exporter


class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.closed = False
        self.error: BaseException | None = None
        self.entered = asyncio.Event()
        self.release: asyncio.Event | None = None
        self.all_headers: list[dict[str, str]] = []
        self.status_code = 200

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.headers = dict(request.headers)
        self.all_headers.append(self.headers)
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return httpx.Response(self.status_code, content=b"opaque", request=request)

    async def aclose(self) -> None:
        self.closed = True


def test_outbound_injects_operation_span_context_and_preserves_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observability, exporter = _observability(monkeypatch)
    inner = _RecordingTransport()
    transport = TracingAsyncTransport.wrap(inner, observability)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post(
                "http://mcp.test/mcp", headers={"x-caller": "preserved"}, content=b"secret"
            )

    asyncio.run(scenario())
    observability.shutdown()
    spans = exporter.get_finished_spans()
    assert inner.headers["x-caller"] == "preserved"
    assert inner.headers["traceparent"].split("-")[2] == f"{spans[0].context.span_id:016x}"
    assert spans[0].kind is SpanKind.CLIENT
    assert inner.closed


def test_wrap_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    observability, _ = _observability(monkeypatch)
    transport = TracingAsyncTransport.wrap(_RecordingTransport(), observability)
    assert TracingAsyncTransport.wrap(transport, observability) is transport


def test_outbound_replaces_stale_mixed_case_w3c_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    observability, _ = _observability(monkeypatch)
    inner = _RecordingTransport()

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=TracingAsyncTransport.wrap(inner, observability)
        ) as client:
            await client.post(
                "http://mcp.test/mcp",
                headers={
                    "TraceParent": "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
                    "TraceState": "private-vendor=stale-secret",
                },
            )

    asyncio.run(scenario())
    observability.shutdown()
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in inner.headers["traceparent"]
    assert "tracestate" not in inner.headers


def test_outbound_replaces_stale_pair_with_coherent_current_tracestate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observability, _ = _observability(monkeypatch)
    inner = _RecordingTransport()
    remote = SpanContext(
        trace_id=int("1" * 32, 16),
        span_id=int("2" * 16, 16),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=TraceState([("current", "safe")]),
    )
    token = otel_context.attach(set_span_in_context(NonRecordingSpan(remote)))

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=TracingAsyncTransport.wrap(inner, observability)
        ) as client:
            await client.post(
                "http://mcp.test/mcp",
                headers={"traceparent": "stale", "tracestate": "stale=private"},
            )

    try:
        asyncio.run(scenario())
    finally:
        otel_context.detach(token)
        observability.shutdown()
    assert inner.headers["tracestate"] == "current=safe"
    assert "stale" not in inner.headers["traceparent"]


def test_disabled_outbound_removes_partial_stale_context() -> None:
    observability = Observability.configure(
        ObservabilitySettings(service_name="mcp-test", service_version="0.3.0", environment="test")
    )
    inner = _RecordingTransport()

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=TracingAsyncTransport.wrap(inner, observability)
        ) as client:
            await client.post("http://mcp.test/mcp", headers={"TraceState": "stale=value"})

    asyncio.run(scenario())
    assert "traceparent" not in inner.headers
    assert "tracestate" not in inner.headers


@pytest.mark.parametrize(
    "status_code,terminal",
    [(204, "completed"), (302, "completed"), (400, "failed"), (503, "failed")],
)
def test_outbound_classifies_http_status_without_body_content(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status_code: int,
    terminal: str,
) -> None:
    observability, exporter = _observability(monkeypatch)
    inner = _RecordingTransport()
    inner.status_code = status_code

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=TracingAsyncTransport.wrap(inner, observability)
        ) as client:
            await client.post("http://mcp.test/mcp", content=b"private-body")

    asyncio.run(scenario())
    observability.shutdown()
    output = capsys.readouterr().out
    assert output.count(f'"event": "mcp.client.streamable_http.{terminal}"') == 1
    assert "private-body" not in output
    assert "private-body" not in str(exporter.get_finished_spans()[0].events)


def test_outbound_failure_is_private_and_has_one_terminal_event(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    observability, exporter = _observability(monkeypatch)
    inner = _RecordingTransport()
    inner.error = RuntimeError("planted-secret-result-and-arguments")
    transport = TracingAsyncTransport.wrap(inner, observability)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(RuntimeError, match="planted-secret"):
                await client.post("http://mcp.test/mcp", content=b"private-payload")

    asyncio.run(scenario())
    observability.shutdown()
    output = capsys.readouterr().out
    span = exporter.get_finished_spans()[0]
    assert output.count('"event": "mcp.client.streamable_http.failed"') == 1
    assert "mcp.client.streamable_http.completed" not in output
    assert "planted-secret" not in output
    assert "private-payload" not in output
    assert "planted-secret" not in str(span.events)
    assert inner.closed


def test_outbound_cancellation_restores_context_and_closes_transport(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    observability, exporter = _observability(monkeypatch)
    inner = _RecordingTransport()
    inner.release = asyncio.Event()
    transport = TracingAsyncTransport.wrap(inner, observability)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            task = asyncio.create_task(client.post("http://mcp.test/mcp"))
            await inner.entered.wait()
            task.cancel("private-cancellation-detail")
            with pytest.raises(asyncio.CancelledError):
                await task
        assert not get_current_span().get_span_context().is_valid

    asyncio.run(scenario())
    observability.shutdown()
    output = capsys.readouterr().out
    assert output.count('"event": "mcp.client.streamable_http.failed"') == 1
    assert "mcp.client.streamable_http.completed" not in output
    assert "private-cancellation-detail" not in output
    assert "private-cancellation-detail" not in str(exporter.get_finished_spans()[0].events)
    assert inner.closed


def test_concurrent_outbound_requests_get_distinct_operation_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observability, exporter = _observability(monkeypatch)
    inner = _RecordingTransport()
    transport = TracingAsyncTransport.wrap(inner, observability)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            await asyncio.gather(
                client.post("http://mcp.test/mcp", headers={"x-request": "one"}),
                client.post("http://mcp.test/mcp", headers={"x-request": "two"}),
            )
        assert not get_current_span().get_span_context().is_valid

    asyncio.run(scenario())
    observability.shutdown()
    span_ids = {f"{span.context.span_id:016x}" for span in exporter.get_finished_spans()}
    propagated_ids = {headers["traceparent"].split("-")[2] for headers in inner.all_headers}
    assert len(span_ids) == 2
    assert propagated_ids == span_ids
    assert inner.closed


def test_base_package_import_does_not_import_optional_mcp_sdk() -> None:
    script = """
import builtins
import json
real_import = builtins.__import__
attempted = []
def guarded(name, *args, **kwargs):
    if name == 'mcp' or name.startswith('mcp.'):
        attempted.append(name)
        raise AssertionError(name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
import a2a_otel_kit
print(json.dumps(attempted))
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and constant test script
        [sys.executable, "-c", script], check=True, capture_output=True, text=True
    )
    assert json.loads(result.stdout) == []


def test_direct_adapter_import_without_mcp_extra_has_clear_error() -> None:
    script = """
import importlib.metadata
real_version = importlib.metadata.version
def missing(name):
    if name == 'mcp':
        raise importlib.metadata.PackageNotFoundError(name)
    return real_version(name)
importlib.metadata.version = missing
try:
    import a2a_otel_kit.adapters.mcp
except ImportError as exc:
    print(str(exc))
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and constant test script
        [sys.executable, "-c", script], check=True, capture_output=True, text=True
    )
    assert "optional 'mcp' extra" in result.stdout
    assert "a2a-otel-kit[mcp]" in result.stdout


def _scope(headers: list[tuple[bytes, bytes]]) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "server": ("test", 80),
        "client": ("test", 1),
        "state": {},
    }


async def _receive() -> ASGIMessage:
    return {"type": "http.request", "body": b"opaque secret", "more_body": False}


async def _send(message: ASGIMessage) -> None:
    del message


def test_inbound_extracts_parent_without_reading_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    observability, exporter = _observability(monkeypatch)
    parent_id = "1111111111111111"
    trace_id = "11111111111111111111111111111111"

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        del scope
        assert (await receive())["body"] == b"opaque secret"
        await send({"type": "http.response.start", "status": 200, "headers": []})

    middleware = TracingASGIMiddleware.wrap(app, observability)
    asyncio.run(
        middleware(
            _scope([(b"traceparent", f"00-{trace_id}-{parent_id}-01".encode())]),
            _receive,
            _send,
        )
    )
    observability.shutdown()
    span = exporter.get_finished_spans()[0]
    assert span.kind is SpanKind.SERVER
    assert f"{span.context.trace_id:032x}" == trace_id
    assert span.parent is not None
    assert f"{span.parent.span_id:016x}" == parent_id


@pytest.mark.parametrize(
    "status_code,terminal",
    [(200, "completed"), (304, "completed"), (404, "failed"), (500, "failed")],
)
def test_inbound_classifies_http_status_and_forwards_message_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status_code: int,
    terminal: str,
) -> None:
    observability, exporter = _observability(monkeypatch)
    sent: list[ASGIMessage] = []
    response = {
        "type": "http.response.start",
        "status": status_code,
        "headers": [(b"x-private", b"planted-secret-header")],
    }

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive
        await send(response)

    async def capture(message: ASGIMessage) -> None:
        sent.append(message)

    asyncio.run(TracingASGIMiddleware.wrap(app, observability)(_scope([]), _receive, capture))
    observability.shutdown()
    output = capsys.readouterr().out
    assert sent == [response]
    assert sent[0] is response
    assert output.count(f'"event": "mcp.server.streamable_http.{terminal}"') == 1
    assert "planted-secret-header" not in output
    assert "planted-secret-header" not in str(exporter.get_finished_spans()[0].events)


def test_cancellation_restores_context_and_records_no_error_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observability, exporter = _observability(monkeypatch)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive, send
        entered.set()
        await release.wait()

    middleware = TracingASGIMiddleware.wrap(app, observability)

    async def scenario() -> None:
        task = asyncio.create_task(middleware(_scope([]), _receive, _send))
        await entered.wait()
        task.cancel("planted-secret")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not get_current_span().get_span_context().is_valid

    asyncio.run(scenario())
    observability.shutdown()
    span = exporter.get_finished_spans()[0]
    assert "planted-secret" not in str(span.events)
    assert "planted-secret" not in str(span.status)


def test_concurrent_inbound_requests_keep_trace_context_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observability, exporter = _observability(monkeypatch)

    entered = 0
    both_entered = asyncio.Event()
    release = asyncio.Event()

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal entered
        del scope, receive, send
        entered += 1
        if entered == 2:
            both_entered.set()
        await release.wait()

    middleware = TracingASGIMiddleware.wrap(app, observability)
    traces = ["1" * 32, "2" * 32]

    async def scenario() -> None:
        requests = asyncio.gather(
            *(
                middleware(
                    _scope([(b"traceparent", f"00-{trace}-{'3' * 16}-01".encode())]),
                    _receive,
                    _send,
                )
                for trace in traces
            )
        )
        await both_entered.wait()
        release.set()
        await requests

    asyncio.run(scenario())
    observability.shutdown()
    assert {f"{span.context.trace_id:032x}" for span in exporter.get_finished_spans()} == set(
        traces
    )
