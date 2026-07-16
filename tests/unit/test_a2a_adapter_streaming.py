"""Regression tests for streaming cleanup, span kind, and event correlation in adapters/a2a.py.

Covers the review findings fixed after the initial Milestone 0.2 implementation: deterministic
inner-iterator cleanup on exhaustion/early-close/cancellation/exception, correct SpanKind per
direction, and started/completed/failed events correlating with the operation's own span. Uses
only in-memory exporters, typed in-process fakes, and `asyncio.Event`-based synchronization - no
network, no Docker, no sleeps, no timing-sensitive assertions.
"""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator

import pytest
from a2a.client.client import Client, ClientCallContext
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers.request_handler import RequestHandler
from a2a.types.a2a_pb2 import (
    AgentCard,
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetExtendedAgentCardRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    ListTaskPushNotificationConfigsRequest,
    ListTaskPushNotificationConfigsResponse,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    SendMessageRequest,
    StreamResponse,
    SubscribeToTaskRequest,
    Task,
    TaskPushNotificationConfig,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode, get_current_span

from a2a_otel_kit.adapters.a2a import TracingClient, TracingRequestHandler
from a2a_otel_kit.application.settings import ObservabilitySettings
from a2a_otel_kit.entrypoints.observability import Observability


class _StreamingFakeClient(Client):
    """A Client whose send_message stream can exhaust, raise, or block indefinitely."""

    def __init__(self) -> None:
        super().__init__()
        self.stream_closed = False
        self.raise_after_first: Exception | None = None
        self.reached_after_first = asyncio.Event()
        self.block_after_first = asyncio.Event()

    async def send_message(
        self, request: SendMessageRequest, *, context: ClientCallContext | None = None
    ) -> AsyncIterator[StreamResponse]:
        try:
            yield StreamResponse()
            if self.raise_after_first is not None:
                raise self.raise_after_first
            self.reached_after_first.set()
            await self.block_after_first.wait()
            yield StreamResponse()
        finally:
            self.stream_closed = True

    def subscribe(
        self, request: SubscribeToTaskRequest, *, context: ClientCallContext | None = None
    ) -> AsyncIterator[StreamResponse]:
        raise NotImplementedError

    async def get_task(
        self, request: GetTaskRequest, *, context: ClientCallContext | None = None
    ) -> Task:
        raise NotImplementedError

    async def cancel_task(
        self, request: CancelTaskRequest, *, context: ClientCallContext | None = None
    ) -> Task:
        raise NotImplementedError

    async def list_tasks(
        self, request: ListTasksRequest, *, context: ClientCallContext | None = None
    ) -> ListTasksResponse:
        raise NotImplementedError

    async def get_task_push_notification_config(
        self,
        request: GetTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> TaskPushNotificationConfig:
        raise NotImplementedError

    async def create_task_push_notification_config(
        self, request: TaskPushNotificationConfig, *, context: ClientCallContext | None = None
    ) -> TaskPushNotificationConfig:
        raise NotImplementedError

    async def list_task_push_notification_configs(
        self,
        request: ListTaskPushNotificationConfigsRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> ListTaskPushNotificationConfigsResponse:
        raise NotImplementedError

    async def delete_task_push_notification_config(
        self,
        request: DeleteTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> None:
        raise NotImplementedError

    async def get_extended_agent_card(
        self,
        request: GetExtendedAgentCardRequest,
        *,
        context: ClientCallContext | None = None,
        signature_verifier: object = None,
    ) -> AgentCard:
        raise NotImplementedError

    async def close(self) -> None:
        pass


class _StreamingFakeRequestHandler(RequestHandler):
    """A RequestHandler whose on_message_send_stream can exhaust, raise, or block indefinitely."""

    def __init__(self) -> None:
        self.stream_closed = False
        self.raise_after_first: Exception | None = None
        self.reached_after_first = asyncio.Event()
        self.block_after_first = asyncio.Event()

    def on_message_send_stream(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> AsyncGenerator[Task]:
        return self._stream()

    async def _stream(self) -> AsyncGenerator[Task]:
        try:
            yield Task(id="fake-task")
            if self.raise_after_first is not None:
                raise self.raise_after_first
            self.reached_after_first.set()
            await self.block_after_first.wait()
            yield Task(id="fake-task-2")
        finally:
            self.stream_closed = True

    async def on_message_send(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> Task | Message:
        raise NotImplementedError

    async def on_get_task(self, params: GetTaskRequest, context: ServerCallContext) -> Task | None:
        raise NotImplementedError

    async def on_cancel_task(
        self, params: CancelTaskRequest, context: ServerCallContext
    ) -> Task | None:
        raise NotImplementedError

    async def on_list_tasks(
        self, params: ListTasksRequest, context: ServerCallContext
    ) -> ListTasksResponse:
        raise NotImplementedError

    def on_subscribe_to_task(
        self, params: SubscribeToTaskRequest, context: ServerCallContext
    ) -> AsyncGenerator[Task]:
        raise NotImplementedError

    async def on_get_extended_agent_card(
        self, params: GetExtendedAgentCardRequest, context: ServerCallContext
    ) -> AgentCard:
        raise NotImplementedError

    async def on_get_task_push_notification_config(
        self, params: GetTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        raise NotImplementedError

    async def on_create_task_push_notification_config(
        self, params: TaskPushNotificationConfig, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        raise NotImplementedError

    async def on_delete_task_push_notification_config(
        self, params: DeleteTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> None:
        raise NotImplementedError

    async def on_list_task_push_notification_configs(
        self, params: ListTaskPushNotificationConfigsRequest, context: ServerCallContext
    ) -> ListTaskPushNotificationConfigsResponse:
        raise NotImplementedError


def _settings(**overrides: object) -> ObservabilitySettings:
    defaults: dict[str, object] = {
        "service_name": "billing",
        "service_version": "1.0.0",
        "environment": "test",
    }
    defaults.update(overrides)
    return ObservabilitySettings(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def traced_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ObservabilitySettings, InMemorySpanExporter]:
    """Settings with tracing enabled, backed by an in-memory exporter for span inspection."""
    exporter = InMemorySpanExporter()
    monkeypatch.setattr("a2a_otel_kit.adapters.tracing.OTLPSpanExporter", lambda **_: exporter)
    settings = _settings(enabled=True, otlp_endpoint="http://localhost:4318")
    return settings, exporter


def _events(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().out.strip().splitlines() if line]


# --- Outbound (client) cleanup -----------------------------------------------------------------


def test_outbound_stream_exhaustion_closes_the_inner_iterator() -> None:
    """Consuming the whole stream closes the inner Client iterator via the finally block."""
    observability = Observability.configure(_settings())
    inner = _StreamingFakeClient()
    inner.block_after_first.set()  # let it run to completion without blocking
    client = TracingClient.wrap(inner, observability)

    async def scenario() -> None:
        async for _ in client.send_message(SendMessageRequest()):
            pass

    asyncio.run(scenario())

    assert inner.stream_closed is True
    observability.shutdown()


def test_outbound_early_aclose_closes_the_inner_iterator() -> None:
    """Calling aclose() on the returned generator after partial consumption still cleans up."""
    observability = Observability.configure(_settings())
    inner = _StreamingFakeClient()
    client = TracingClient.wrap(inner, observability)

    async def scenario() -> None:
        gen = client.send_message(SendMessageRequest())
        async for _ in gen:
            break
        await gen.aclose()  # type: ignore[attr-defined]

    asyncio.run(scenario())

    assert inner.stream_closed is True
    observability.shutdown()


def test_outbound_exception_during_iteration_closes_iterator_and_restores_context(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
) -> None:
    """An exception raised mid-stream still closes the iterator and detaches the span context."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)
    inner = _StreamingFakeClient()
    inner.raise_after_first = RuntimeError("leaked-secret-do-not-record")
    client = TracingClient.wrap(inner, observability)

    async def scenario() -> None:
        async for _ in client.send_message(SendMessageRequest()):
            pass

    with pytest.raises(RuntimeError, match="leaked-secret-do-not-record"):
        asyncio.run(scenario())
    observability.flush()

    assert inner.stream_closed is True
    assert get_current_span().get_span_context().is_valid is False

    (span,) = [s for s in exporter.get_finished_spans() if s.name == "a2a.client.send_message"]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description is None
    assert span.events == ()
    observability.shutdown()


async def _consume_until_cancelled(
    stream: object, results: list[object], started: asyncio.Event
) -> None:
    async for item in stream:  # type: ignore[attr-defined]
        results.append(item)
        started.set()


def test_outbound_cancellation_closes_iterator_and_restores_ambient_context(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
) -> None:
    """Cancelling the consuming task closes the inner iterator and detaches the OTel context."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)
    inner = _StreamingFakeClient()
    client = TracingClient.wrap(inner, observability)
    results: list[object] = []
    started = asyncio.Event()

    async def scenario() -> None:
        gen = client.send_message(SendMessageRequest())
        task = asyncio.create_task(_consume_until_cancelled(gen, results, started))
        await started.wait()
        await inner.reached_after_first.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    observability.flush()

    assert inner.stream_closed is True
    assert len(results) == 1
    assert get_current_span().get_span_context().is_valid is False

    (span,) = [s for s in exporter.get_finished_spans() if s.name == "a2a.client.send_message"]
    assert span.status.status_code == StatusCode.ERROR
    observability.shutdown()


def test_no_context_leaks_into_a_subsequent_operation_after_cancellation(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
) -> None:
    """A cancelled stream's context does not leak into a later, independent operation."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)
    inner = _StreamingFakeClient()
    client = TracingClient.wrap(inner, observability)
    results: list[object] = []
    started = asyncio.Event()

    async def scenario() -> None:
        gen = client.send_message(SendMessageRequest())
        task = asyncio.create_task(_consume_until_cancelled(gen, results, started))
        await started.wait()
        await inner.reached_after_first.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # A brand-new, independent operation after the cancellation must start a fresh trace.
        next_inner = _StreamingFakeClient()
        next_inner.block_after_first.set()
        next_client = TracingClient.wrap(next_inner, observability)
        async for _ in next_client.send_message(SendMessageRequest()):
            pass

    asyncio.run(scenario())
    observability.flush()

    spans = [s for s in exporter.get_finished_spans() if s.name == "a2a.client.send_message"]
    assert len(spans) == 2
    cancelled_span, completed_span = spans
    assert cancelled_span.context.trace_id != completed_span.context.trace_id
    assert completed_span.parent is None
    observability.shutdown()


# --- Inbound (server) cleanup -------------------------------------------------------------------


def test_inbound_stream_exhaustion_closes_the_inner_iterator() -> None:
    """Consuming the whole stream closes the inner RequestHandler iterator."""
    observability = Observability.configure(_settings())
    inner = _StreamingFakeRequestHandler()
    inner.block_after_first.set()
    handler = TracingRequestHandler.wrap(inner, observability)
    context = ServerCallContext(state={})

    async def scenario() -> None:
        async for _ in handler.on_message_send_stream(SendMessageRequest(), context):
            pass

    asyncio.run(scenario())

    assert inner.stream_closed is True
    observability.shutdown()


def test_inbound_early_aclose_closes_the_inner_iterator() -> None:
    """Calling aclose() on the handler's returned generator still cleans up the inner iterator."""
    observability = Observability.configure(_settings())
    inner = _StreamingFakeRequestHandler()
    handler = TracingRequestHandler.wrap(inner, observability)
    context = ServerCallContext(state={})

    async def scenario() -> None:
        gen = handler.on_message_send_stream(SendMessageRequest(), context)
        async for _ in gen:
            break
        await gen.aclose()

    asyncio.run(scenario())

    assert inner.stream_closed is True
    observability.shutdown()


# --- Span kind ------------------------------------------------------------------------------


def test_outbound_spans_use_client_kind(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
) -> None:
    """Every span TracingClient creates uses SpanKind.CLIENT."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)
    inner = _StreamingFakeClient()
    inner.block_after_first.set()
    client = TracingClient.wrap(inner, observability)

    asyncio.run(_drain(client.send_message(SendMessageRequest())))
    observability.flush()

    (span,) = [s for s in exporter.get_finished_spans() if s.name == "a2a.client.send_message"]
    assert span.kind == SpanKind.CLIENT
    observability.shutdown()


def test_inbound_spans_use_server_kind(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
) -> None:
    """Every span TracingRequestHandler creates uses SpanKind.SERVER."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)
    inner = _StreamingFakeRequestHandler()
    inner.block_after_first.set()
    handler = TracingRequestHandler.wrap(inner, observability)
    context = ServerCallContext(state={})

    asyncio.run(_drain(handler.on_message_send_stream(SendMessageRequest(), context)))
    observability.flush()

    (span,) = [
        s for s in exporter.get_finished_spans() if s.name == "a2a.server.on_message_send_stream"
    ]
    assert span.kind == SpanKind.SERVER
    observability.shutdown()


async def _drain(stream: object) -> None:
    async for _ in stream:  # type: ignore[attr-defined]
        pass


# --- Event/span correlation and single-terminal-event guarantees ----------------------------


def test_started_and_terminal_events_correlate_with_the_operation_span(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """started/completed both carry the exact trace_id/span_id of the operation's own span."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)
    inner = _StreamingFakeClient()
    inner.block_after_first.set()
    client = TracingClient.wrap(inner, observability)

    asyncio.run(_drain(client.send_message(SendMessageRequest())))
    observability.flush()

    (span,) = [s for s in exporter.get_finished_spans() if s.name == "a2a.client.send_message"]
    expected_trace_id = format(span.context.trace_id, "032x")
    expected_span_id = format(span.context.span_id, "016x")

    events = _events(capsys)
    relevant = [e for e in events if e["operation"] == "a2a.client.send_message"]
    assert [e["event"] for e in relevant] == [
        "a2a.client.send_message.started",
        "a2a.client.send_message.completed",
    ]
    for event in relevant:
        assert event["trace_id"] == expected_trace_id
        assert event["span_id"] == expected_span_id
    observability.shutdown()


def test_exactly_one_terminal_event_on_early_close(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An early aclose() emits started + exactly one terminal event (failed), never both."""
    settings, _ = traced_settings
    observability = Observability.configure(settings)
    inner = _StreamingFakeClient()
    client = TracingClient.wrap(inner, observability)

    async def scenario() -> None:
        gen = client.send_message(SendMessageRequest())
        async for _ in gen:
            break
        await gen.aclose()  # type: ignore[attr-defined]

    asyncio.run(scenario())

    events = [e["event"] for e in _events(capsys)]
    assert events == ["a2a.client.send_message.started", "a2a.client.send_message.failed"]
    observability.shutdown()


def test_exactly_one_terminal_event_on_exhaustion(capsys: pytest.CaptureFixture[str]) -> None:
    """Full exhaustion emits started + exactly one terminal event (completed), never both."""
    observability = Observability.configure(_settings())
    inner = _StreamingFakeClient()
    inner.block_after_first.set()
    client = TracingClient.wrap(inner, observability)

    asyncio.run(_drain(client.send_message(SendMessageRequest())))

    events = [e["event"] for e in _events(capsys)]
    assert events == ["a2a.client.send_message.started", "a2a.client.send_message.completed"]
    observability.shutdown()


def test_no_sensitive_content_in_events_or_spans_on_streaming_failure(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A streaming failure's exception message never reaches a structured event or span."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)
    inner = _StreamingFakeClient()
    inner.raise_after_first = RuntimeError("api-key=super-secret-value")
    client = TracingClient.wrap(inner, observability)

    async def scenario() -> None:
        async for _ in client.send_message(SendMessageRequest()):
            pass

    with pytest.raises(RuntimeError):
        asyncio.run(scenario())
    observability.flush()

    output = capsys.readouterr().out
    assert "super-secret-value" not in output

    (span,) = [s for s in exporter.get_finished_spans() if s.name == "a2a.client.send_message"]
    assert span.events == ()
    assert span.status.description is None
    observability.shutdown()
