"""Tests for the optional A2A SDK adapter (adapters/a2a.py).

Uses minimal in-process fake ``Client``/``RequestHandler`` implementations - no real transport,
no network, no Docker. The "enabled" tracing path patches the concrete OTLP exporter used inside
``a2a_otel_kit.adapters.tracing`` for an ``InMemorySpanExporter``, exactly as in
``test_observability.py``.
"""

import asyncio
import importlib.util
import json
import socket
import sys
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
from opentelemetry.trace import StatusCode

from a2a_otel_kit import inject_trace_context
from a2a_otel_kit.adapters.a2a import TracingClient, TracingRequestHandler
from a2a_otel_kit.application.settings import ObservabilitySettings
from a2a_otel_kit.entrypoints.observability import Observability


class _FakeClient(Client):
    """Minimal Client implementing every abstract method, tracking which ones were called."""

    def __init__(self) -> None:
        super().__init__()
        self.seen_context: ClientCallContext | None = None
        self.result: Task = Task(id="fake-task")
        self.error: Exception | None = None
        self.calls: list[str] = []

    async def get_task(
        self, request: GetTaskRequest, *, context: ClientCallContext | None = None
    ) -> Task:
        self.calls.append("get_task")
        self.seen_context = context
        if self.error is not None:
            raise self.error
        return self.result

    async def send_message(
        self, request: SendMessageRequest, *, context: ClientCallContext | None = None
    ) -> AsyncIterator[StreamResponse]:
        self.calls.append("send_message")
        yield StreamResponse()

    def subscribe(
        self, request: SubscribeToTaskRequest, *, context: ClientCallContext | None = None
    ) -> AsyncIterator[StreamResponse]:
        self.calls.append("subscribe")

        async def _empty() -> AsyncIterator[StreamResponse]:
            return
            yield  # pragma: no cover - makes this an async generator

        return _empty()

    async def cancel_task(
        self, request: CancelTaskRequest, *, context: ClientCallContext | None = None
    ) -> Task:
        self.calls.append("cancel_task")
        return self.result

    async def list_tasks(
        self, request: ListTasksRequest, *, context: ClientCallContext | None = None
    ) -> ListTasksResponse:
        self.calls.append("list_tasks")
        return ListTasksResponse()

    async def get_task_push_notification_config(
        self,
        request: GetTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> TaskPushNotificationConfig:
        self.calls.append("get_task_push_notification_config")
        return TaskPushNotificationConfig()

    async def create_task_push_notification_config(
        self, request: TaskPushNotificationConfig, *, context: ClientCallContext | None = None
    ) -> TaskPushNotificationConfig:
        self.calls.append("create_task_push_notification_config")
        return TaskPushNotificationConfig()

    async def list_task_push_notification_configs(
        self,
        request: ListTaskPushNotificationConfigsRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> ListTaskPushNotificationConfigsResponse:
        self.calls.append("list_task_push_notification_configs")
        return ListTaskPushNotificationConfigsResponse()

    async def delete_task_push_notification_config(
        self,
        request: DeleteTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> None:
        self.calls.append("delete_task_push_notification_config")

    async def get_extended_agent_card(
        self,
        request: GetExtendedAgentCardRequest,
        *,
        context: ClientCallContext | None = None,
        signature_verifier: object = None,
    ) -> AgentCard:
        self.calls.append("get_extended_agent_card")
        return AgentCard()

    async def close(self) -> None:
        self.calls.append("close")


class _FakeRequestHandler(RequestHandler):
    """Minimal RequestHandler implementing every abstract method, tracking calls made."""

    def __init__(self) -> None:
        self.seen_context: ServerCallContext | None = None
        self.result: Task | None = Task(id="fake-task")
        self.error: Exception | None = None
        self.calls: list[str] = []

    async def on_get_task(self, params: GetTaskRequest, context: ServerCallContext) -> Task | None:
        self.calls.append("on_get_task")
        self.seen_context = context
        if self.error is not None:
            raise self.error
        return self.result

    async def on_message_send(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> Task | Message:
        self.calls.append("on_message_send")
        return Task(id="fake-task")

    def on_message_send_stream(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> AsyncGenerator[Task]:
        self.calls.append("on_message_send_stream")

        async def _empty() -> AsyncGenerator[Task]:
            return
            yield  # pragma: no cover - makes this an async generator

        return _empty()

    async def on_cancel_task(
        self, params: CancelTaskRequest, context: ServerCallContext
    ) -> Task | None:
        self.calls.append("on_cancel_task")
        return Task(id="fake-task")

    async def on_list_tasks(
        self, params: ListTasksRequest, context: ServerCallContext
    ) -> ListTasksResponse:
        self.calls.append("on_list_tasks")
        return ListTasksResponse()

    def on_subscribe_to_task(
        self, params: SubscribeToTaskRequest, context: ServerCallContext
    ) -> AsyncGenerator[Task]:
        self.calls.append("on_subscribe_to_task")

        async def _empty() -> AsyncGenerator[Task]:
            return
            yield  # pragma: no cover - makes this an async generator

        return _empty()

    async def on_get_extended_agent_card(
        self, params: GetExtendedAgentCardRequest, context: ServerCallContext
    ) -> AgentCard:
        self.calls.append("on_get_extended_agent_card")
        return AgentCard()

    async def on_get_task_push_notification_config(
        self, params: GetTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        self.calls.append("on_get_task_push_notification_config")
        return TaskPushNotificationConfig()

    async def on_create_task_push_notification_config(
        self, params: TaskPushNotificationConfig, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        self.calls.append("on_create_task_push_notification_config")
        return TaskPushNotificationConfig()

    async def on_delete_task_push_notification_config(
        self, params: DeleteTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> None:
        self.calls.append("on_delete_task_push_notification_config")

    async def on_list_task_push_notification_configs(
        self, params: ListTaskPushNotificationConfigsRequest, context: ServerCallContext
    ) -> ListTaskPushNotificationConfigsResponse:
        self.calls.append("on_list_task_push_notification_configs")
        return ListTaskPushNotificationConfigsResponse()


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


def test_public_adapter_imports_when_a2a_sdk_is_installed() -> None:
    """The adapter module imports cleanly and its classes subclass the SDK's ABCs."""
    assert issubclass(TracingClient, Client)
    assert issubclass(TracingRequestHandler, RequestHandler)


def test_adapter_import_raises_a_clear_error_without_a2a_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing the adapter without the optional a2a-sdk dependency fails with a clear message."""
    # Clear every already-cached a2a.* submodule first: otherwise `from a2a.client.client import
    # ...` resolves straight from sys.modules and never re-triggers the `import a2a` this test
    # needs to fail.
    for name in list(sys.modules):
        if name == "a2a" or name.startswith("a2a."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "a2a", None)
    spec = importlib.util.find_spec("a2a_otel_kit.adapters.a2a")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    with pytest.raises(ImportError, match=r"a2a.*extra"):
        spec.loader.exec_module(module)


def test_adapter_import_performs_no_network_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing the adapter module must never open a socket."""

    def _blocked(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("network I/O attempted during import")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)

    spec = importlib.util.find_spec("a2a_otel_kit.adapters.a2a")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # must not raise


def test_wrapping_an_already_wrapped_client_is_idempotent() -> None:
    """wrap() called twice on the same client returns the same instance, avoiding double spans."""
    observability = Observability.configure(_settings())
    inner = _FakeClient()

    wrapped_once = TracingClient.wrap(inner, observability)
    wrapped_twice = TracingClient.wrap(wrapped_once, observability)

    assert wrapped_once is wrapped_twice
    observability.shutdown()


def test_wrapping_an_already_wrapped_handler_is_idempotent() -> None:
    """wrap() called twice on the same handler returns the same instance."""
    observability = Observability.configure(_settings())
    inner = _FakeRequestHandler()

    wrapped_once = TracingRequestHandler.wrap(inner, observability)
    wrapped_twice = TracingRequestHandler.wrap(wrapped_once, observability)

    assert wrapped_once is wrapped_twice
    observability.shutdown()


def test_disabled_observability_is_a_safe_no_op_for_the_client() -> None:
    """Disabled observability never requires exporter configuration and never raises."""
    observability = Observability.configure(_settings())
    inner = _FakeClient()
    client = TracingClient.wrap(inner, observability)

    result = asyncio.run(client.get_task(GetTaskRequest(id="t1")))

    assert result == inner.result
    assert inner.seen_context is not None
    assert "traceparent" not in (inner.seen_context.service_parameters or {})
    observability.shutdown()


def test_outbound_injection_targets_the_operations_own_span(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
) -> None:
    """The traceparent injected into service_parameters matches this call's own span."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)
    inner = _FakeClient()
    client = TracingClient.wrap(inner, observability)

    asyncio.run(client.get_task(GetTaskRequest(id="t1")))
    observability.flush()

    assert inner.seen_context is not None
    injected = inner.seen_context.service_parameters or {}
    assert "traceparent" in injected

    (span,) = [s for s in exporter.get_finished_spans() if s.name == "a2a.client.get_task"]
    expected_trace_id = format(span.context.trace_id, "032x")
    assert expected_trace_id in injected["traceparent"]
    observability.shutdown()


def test_outbound_injection_preserves_existing_service_parameters(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
) -> None:
    """Injection merges into caller-supplied service_parameters instead of replacing them."""
    settings, _ = traced_settings
    observability = Observability.configure(settings)
    inner = _FakeClient()
    client = TracingClient.wrap(inner, observability)
    caller_context = ClientCallContext(service_parameters={"x-tenant": "acme"})

    asyncio.run(client.get_task(GetTaskRequest(id="t1"), context=caller_context))
    observability.shutdown()

    injected = inner.seen_context.service_parameters or {}  # type: ignore[union-attr]
    assert injected["x-tenant"] == "acme"
    assert "traceparent" in injected
    assert caller_context.service_parameters == {"x-tenant": "acme"}, "caller's dict was mutated"


def test_outbound_injection_deterministically_overwrites_a_stale_traceparent(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
) -> None:
    """A pre-existing traceparent in service_parameters is replaced by the current span."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)
    inner = _FakeClient()
    client = TracingClient.wrap(inner, observability)
    stale_context = ClientCallContext(
        service_parameters={
            "traceparent": "00-11111111111111111111111111111111-2222222222222222-01"
        }
    )

    asyncio.run(client.get_task(GetTaskRequest(id="t1"), context=stale_context))
    observability.flush()

    (span,) = [s for s in exporter.get_finished_spans() if s.name == "a2a.client.get_task"]
    expected_trace_id = format(span.context.trace_id, "032x")
    injected = inner.seen_context.service_parameters or {}  # type: ignore[union-attr]
    assert "11111111111111111111111111111111" not in injected["traceparent"]
    assert expected_trace_id in injected["traceparent"]
    observability.shutdown()


def test_inbound_extraction_gives_the_wrapped_handler_a_child_span(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
) -> None:
    """A span started inside the wrapped handler is a child of the caller's injected span."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)
    inner = _FakeRequestHandler()
    handler = TracingRequestHandler.wrap(inner, observability)

    carrier: dict[str, str] = {}
    with observability.start_span("caller-span") as caller_span:
        inject_trace_context(carrier)
        caller_span_id = caller_span.get_span_context().span_id
        caller_trace_id = caller_span.get_span_context().trace_id

    server_context = ServerCallContext(state={"headers": carrier})
    asyncio.run(handler.on_get_task(GetTaskRequest(id="t1"), server_context))
    observability.flush()

    (server_span,) = [
        s for s in exporter.get_finished_spans() if s.name == "a2a.server.on_get_task"
    ]
    assert server_span.context.trace_id == caller_trace_id
    assert server_span.parent is not None
    assert server_span.parent.span_id == caller_span_id
    observability.shutdown()


def test_inbound_extraction_ignores_non_string_and_missing_headers() -> None:
    """Untrusted, malformed, or absent header state is handled deterministically, not fatally."""
    observability = Observability.configure(_settings())
    inner = _FakeRequestHandler()
    handler = TracingRequestHandler.wrap(inner, observability)

    context_without_headers = ServerCallContext(state={})
    result = asyncio.run(handler.on_get_task(GetTaskRequest(id="t1"), context_without_headers))
    assert result == inner.result

    context_with_malformed_headers = ServerCallContext(
        state={"headers": {"x": 123, "traceparent": None}}
    )
    result = asyncio.run(
        handler.on_get_task(GetTaskRequest(id="t1"), context_with_malformed_headers)
    )
    assert result == inner.result
    observability.shutdown()


def test_concurrent_client_calls_do_not_share_injected_trace_context(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
) -> None:
    """Two concurrent calls each inject their own span's trace context, never mixed up."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)

    async def call_once() -> dict[str, str]:
        inner = _FakeClient()
        client = TracingClient.wrap(inner, observability)
        await client.get_task(GetTaskRequest(id="t1"))
        return dict(inner.seen_context.service_parameters or {})  # type: ignore[union-attr]

    async def run_concurrently() -> tuple[dict[str, str], dict[str, str]]:
        return await asyncio.gather(call_once(), call_once())

    first, second = asyncio.run(run_concurrently())
    observability.flush()

    assert first["traceparent"] != second["traceparent"]
    trace_ids = {span.name: span.context.trace_id for span in exporter.get_finished_spans()}
    assert len({s.context.trace_id for s in exporter.get_finished_spans()}) == 2
    del trace_ids
    observability.shutdown()


def test_successful_call_leaves_the_span_without_an_error_status(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
) -> None:
    """A successful operation's span does not carry an ERROR status."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)
    inner = _FakeClient()
    client = TracingClient.wrap(inner, observability)

    asyncio.run(client.get_task(GetTaskRequest(id="t1")))
    observability.flush()

    (span,) = [s for s in exporter.get_finished_spans() if s.name == "a2a.client.get_task"]
    assert span.status.status_code != StatusCode.ERROR
    observability.shutdown()


def test_failed_call_marks_the_span_as_error_without_leaking_exception_content(
    traced_settings: tuple[ObservabilitySettings, InMemorySpanExporter],
) -> None:
    """A raised exception propagates unchanged, but its message never reaches the span."""
    settings, exporter = traced_settings
    observability = Observability.configure(settings)
    inner = _FakeClient()
    inner.error = RuntimeError("leaked-secret-do-not-record")
    client = TracingClient.wrap(inner, observability)

    with pytest.raises(RuntimeError, match="leaked-secret-do-not-record"):
        asyncio.run(client.get_task(GetTaskRequest(id="t1")))
    observability.flush()

    (span,) = [s for s in exporter.get_finished_spans() if s.name == "a2a.client.get_task"]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description is None
    assert span.events == ()
    observability.shutdown()


def test_structured_events_cover_start_success_and_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """emit_event fires a started event and either a completed or a failed event, never both."""
    observability = Observability.configure(_settings())
    inner = _FakeClient()
    client = TracingClient.wrap(inner, observability)

    asyncio.run(client.get_task(GetTaskRequest(id="t1")))
    success_lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    success_events = [line["event"] for line in success_lines]
    assert success_events == ["a2a.client.get_task.started", "a2a.client.get_task.completed"]

    inner.error = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        asyncio.run(client.get_task(GetTaskRequest(id="t1")))
    failure_lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    failure_events = [line["event"] for line in failure_lines]
    assert failure_events == ["a2a.client.get_task.started", "a2a.client.get_task.failed"]
    observability.shutdown()


def test_structured_events_carry_only_the_allowlisted_operation_field(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No payload, task, or exception content appears in the emitted structured events."""
    observability = Observability.configure(_settings())
    inner = _FakeClient()
    client = TracingClient.wrap(inner, observability)

    asyncio.run(client.get_task(GetTaskRequest(id="t1")))
    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]

    expected_keys = {
        "event",
        "schema_version",
        "event_outcome",
        "operation",
        "service",
        "environment",
        "version",
        "level",
        "logger",
        "timestamp",
    }
    for line in lines:
        assert set(line.keys()) <= expected_keys
        assert line["operation"] == "a2a.client.get_task"
    observability.shutdown()


async def _exercise_every_client_method(client: Client) -> None:
    """Call every Client method once with minimal, valid protobuf requests."""
    async for _ in client.send_message(SendMessageRequest()):
        pass
    async for _ in client.subscribe(SubscribeToTaskRequest()):
        pass
    await client.get_task(GetTaskRequest())
    await client.cancel_task(CancelTaskRequest())
    await client.list_tasks(ListTasksRequest())
    await client.get_task_push_notification_config(GetTaskPushNotificationConfigRequest())
    await client.create_task_push_notification_config(TaskPushNotificationConfig())
    await client.list_task_push_notification_configs(ListTaskPushNotificationConfigsRequest())
    await client.delete_task_push_notification_config(DeleteTaskPushNotificationConfigRequest())
    await client.get_extended_agent_card(GetExtendedAgentCardRequest())
    await client.close()


def test_every_client_method_is_delegated_and_traced(capsys: pytest.CaptureFixture[str]) -> None:
    """Every Client method reaches the wrapped inner client and emits a started/completed pair."""
    observability = Observability.configure(_settings())
    inner = _FakeClient()
    client = TracingClient.wrap(inner, observability)

    asyncio.run(_exercise_every_client_method(client))
    observability.shutdown()

    assert inner.calls == [
        "send_message",
        "subscribe",
        "get_task",
        "cancel_task",
        "list_tasks",
        "get_task_push_notification_config",
        "create_task_push_notification_config",
        "list_task_push_notification_configs",
        "delete_task_push_notification_config",
        "get_extended_agent_card",
        "close",
    ]
    events = [json.loads(line)["event"] for line in capsys.readouterr().out.strip().splitlines()]
    # "close" is a plain passthrough (no request/response to correlate) and is not traced.
    for operation in inner.calls[:-1]:
        assert f"a2a.client.{operation}.started" in events
        assert f"a2a.client.{operation}.completed" in events


async def _exercise_every_handler_method(handler: RequestHandler) -> None:
    """Call every RequestHandler method once with minimal, valid protobuf params."""
    context = ServerCallContext(state={})
    await handler.on_message_send(SendMessageRequest(), context)
    async for _ in handler.on_message_send_stream(SendMessageRequest(), context):
        pass
    await handler.on_get_task(GetTaskRequest(), context)
    await handler.on_cancel_task(CancelTaskRequest(), context)
    await handler.on_list_tasks(ListTasksRequest(), context)
    async for _ in handler.on_subscribe_to_task(SubscribeToTaskRequest(), context):
        pass
    await handler.on_get_extended_agent_card(GetExtendedAgentCardRequest(), context)
    await handler.on_get_task_push_notification_config(
        GetTaskPushNotificationConfigRequest(), context
    )
    await handler.on_create_task_push_notification_config(TaskPushNotificationConfig(), context)
    await handler.on_delete_task_push_notification_config(
        DeleteTaskPushNotificationConfigRequest(), context
    )
    await handler.on_list_task_push_notification_configs(
        ListTaskPushNotificationConfigsRequest(), context
    )


def test_every_handler_method_is_delegated_and_traced(capsys: pytest.CaptureFixture[str]) -> None:
    """Every RequestHandler method reaches the wrapped inner handler and is traced."""
    observability = Observability.configure(_settings())
    inner = _FakeRequestHandler()
    handler = TracingRequestHandler.wrap(inner, observability)

    asyncio.run(_exercise_every_handler_method(handler))
    observability.shutdown()

    assert inner.calls == [
        "on_message_send",
        "on_message_send_stream",
        "on_get_task",
        "on_cancel_task",
        "on_list_tasks",
        "on_subscribe_to_task",
        "on_get_extended_agent_card",
        "on_get_task_push_notification_config",
        "on_create_task_push_notification_config",
        "on_delete_task_push_notification_config",
        "on_list_task_push_notification_configs",
    ]
    events = [json.loads(line)["event"] for line in capsys.readouterr().out.strip().splitlines()]
    for operation in inner.calls:
        assert f"a2a.server.{operation}.started" in events
        assert f"a2a.server.{operation}.completed" in events
