"""Optional OpenTelemetry integration for the official A2A Python SDK.

Requires the ``a2a`` extra: ``pip install a2a-otel-kit[a2a]`` (or ``uv add a2a-otel-kit[a2a]``).
The base ``a2a_otel_kit`` package never imports this module, so installing ``a2a-sdk`` has no
effect on callers who only use the Milestone 0.1 foundation.

Verified against ``a2a-sdk`` 1.1.1. Supported extension points:

- **Client (outbound):** ``a2a.client.client.Client``, an abstract base class with 11 methods.
  :class:`TracingClient` wraps a concrete ``Client`` instance and delegates every method,
  injecting the current W3C trace context into ``ClientCallContext.service_parameters`` - the
  same field the SDK's own ``get_http_args()`` copies into the outbound HTTP ``headers`` for the
  JSON-RPC and REST transports.
- **Server (inbound, JSON-RPC/REST only):** ``a2a.server.request_handlers.request_handler``'s
  ``RequestHandler``, an abstract base class with 11 methods. :class:`TracingRequestHandler`
  wraps a concrete ``RequestHandler`` and delegates every method, extracting a W3C trace context
  from ``ServerCallContext.state['headers']`` - populated with the real inbound HTTP headers by
  the SDK's ``DefaultServerCallContextBuilder`` for both the JSON-RPC and REST FastAPI routes.

**Not covered:** the gRPC transport builds its ``ServerCallContext`` from gRPC servicer context
instead of Starlette request headers (see ``a2a.server.request_handlers.grpc_handler``), so this
adapter does not extract trace context for gRPC-originated requests. Wrapping a gRPC-backed
``RequestHandler`` still works and still produces spans/events; only inbound trace-context
continuity is unverified for that transport.

**Why not the SDK's own ``ClientCallInterceptor``:** it is the SDK's documented hook for tracing,
but ``BaseClient._execute_with_interceptors`` calls the transport with no ``try/except`` around
it, so ``ClientCallInterceptor.after()`` is never invoked when the transport raises. Using it for
span lifetime would leak an unclosed span and an undetached OpenTelemetry context on every failed
call. This adapter instead wraps the whole ``Client``/``RequestHandler`` so every span is opened
and closed within a single ``try/except/finally`` this library controls.

Recorded telemetry is metadata-only: span names are fixed strings such as
``"a2a.client.send_message"`` (built from the SDK's own method names, never remote-supplied
data), and the only attribute recorded is ``operation`` (the same fixed name). No message body,
artifact, task text, agent name, URL, header value, or exception message is ever recorded; a
failure sets an ERROR span status with no description and emits a structured event carrying only
``operation``.

**Streaming cleanup and terminal-outcome policy:** every streaming operation owns exactly one
inner async iterator (obtained by calling the wrapped ``Client``/``RequestHandler`` method once)
and closes it deterministically in a ``finally`` block - on full exhaustion, on an exception
raised during iteration, on an explicit ``aclose()`` from the consumer, and on task cancellation
alike. This library never relies on garbage collection or implicit async-generator finalization
for cleanup (see ``a2a.client.transports.http_helpers._SSEEventSource``'s docstring for why the
SDK itself avoids bare generator-based cleanup for its own SSE connections - the same class of
bug this adapter guards against for the iterator it owns). Terminal-outcome policy: a stream
that is fully exhausted is ``completed``/SUCCESS; anything else - an exception, an explicit
``aclose()``, or cancellation - is ``failed``/ERROR. Exactly one terminal event is ever emitted
per operation; ``started`` is always emitted first, inside the operation's own span, so all three
events (and the span itself) share the same ``trace_id``/``span_id``. See ADR-0003 for the full
rationale.
"""

from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractContextManager, nullcontext

from opentelemetry.trace import SpanKind, StatusCode

try:
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
        TaskArtifactUpdateEvent,
        TaskPushNotificationConfig,
        TaskStatusUpdateEvent,
    )
except ImportError as exc:
    raise ImportError(
        "a2a_otel_kit.adapters.a2a requires the optional 'a2a' extra: install with "
        "`pip install a2a-otel-kit[a2a]` (or `uv add a2a-otel-kit[a2a]`)."
    ) from exc

from a2a_otel_kit.adapters.propagation import continue_trace, inject_trace_context
from a2a_otel_kit.application.ports import ObservabilityFacade
from a2a_otel_kit.domain.attributes import StructuredEventOutcome

_ServerEvent = Message | Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent


async def _run_traced[T](
    observability: ObservabilityFacade,
    operation: str,
    kind: SpanKind,
    invoke: Callable[[], Awaitable[T]],
) -> T:
    """Run one non-streaming operation inside a span, emitting start/success/failure events.

    ``started`` is emitted inside the span so it - like ``completed``/``failed`` - correlates
    with this operation's own ``trace_id``/``span_id``, not whatever span happened to be ambient
    before this call. ``BaseException`` (not ``Exception``) is caught so task cancellation gets
    the same defined ``failed`` terminal outcome as any other non-success completion; the
    original exception or cancellation always propagates unchanged.
    """
    with observability.start_span(
        operation, kind=kind, attributes={"operation": operation}, record_exception=False
    ) as span:
        observability.emit_event(
            operation + ".started", StructuredEventOutcome.STARTED, operation=operation
        )
        try:
            result = await invoke()
        except BaseException:
            span.set_status(StatusCode.ERROR)
            observability.emit_event(
                operation + ".failed", StructuredEventOutcome.ERROR, operation=operation
            )
            raise
        observability.emit_event(
            operation + ".completed", StructuredEventOutcome.SUCCESS, operation=operation
        )
        return result


async def _stream_traced[T](
    observability: ObservabilityFacade,
    operation: str,
    kind: SpanKind,
    invoke: Callable[[], AsyncIterator[T]],
    *,
    ambient: AbstractContextManager[None],
) -> AsyncGenerator[T]:
    """Run one streaming operation inside a span, with deterministic inner-iterator cleanup.

    ``ambient`` is entered before the span (and exited after it), so a caller-provided context -
    :class:`~a2a_otel_kit.adapters.propagation.continue_trace` on the server side, a no-op
    :func:`contextlib.nullcontext` on the client side - is active for the span's entire lifetime.

    This function owns exactly one inner iterator, obtained once via ``invoke()``, and closes it
    in a ``finally`` block regardless of how iteration ends: full exhaustion, an exception, an
    explicit ``aclose()`` from the consumer, or task cancellation. Terminal-outcome policy: only
    full exhaustion is ``completed``/SUCCESS; every other ending - exception, ``aclose()``, or
    cancellation - is ``failed``/ERROR. This is a single, deliberate library-wide policy (see
    ADR-0003) so an operation never emits more than one terminal event and "failed" always means
    "did not fully complete," full stop. ``except BaseException`` (not ``Exception``) is required
    to give ``GeneratorExit``/``CancelledError`` the same defined outcome; both are re-raised
    unchanged after cleanup, never swallowed.
    """
    with (
        ambient,
        observability.start_span(
            operation, kind=kind, attributes={"operation": operation}, record_exception=False
        ) as span,
    ):
        observability.emit_event(
            operation + ".started", StructuredEventOutcome.STARTED, operation=operation
        )
        iterator = invoke()
        try:
            async for item in iterator:
                yield item
        except BaseException:
            span.set_status(StatusCode.ERROR)
            observability.emit_event(
                operation + ".failed", StructuredEventOutcome.ERROR, operation=operation
            )
            raise
        else:
            observability.emit_event(
                operation + ".completed", StructuredEventOutcome.SUCCESS, operation=operation
            )
        finally:
            # AsyncIterator (what every wrapped Client/RequestHandler method is typed to return)
            # does not guarantee aclose(); AsyncGenerator does, and every concrete iterator this
            # adapter has been verified against is one. Close it when supported rather than
            # assuming a narrower type than the ABC actually declares.
            aclose = getattr(iterator, "aclose", None)
            if aclose is not None:
                await aclose()


class TracingClient(Client):
    """Wraps a concrete A2A ``Client``, adding spans, W3C injection, and structured events.

    Every abstract ``Client`` method is delegated to the wrapped instance. Nothing about the
    request or response payload is inspected; only the current trace context is merged into the
    call's ``service_parameters``.
    """

    def __init__(self, inner: Client, observability: ObservabilityFacade) -> None:
        """Wrap ``inner`` directly; prefer :meth:`wrap` to avoid double-instrumenting."""
        super().__init__()
        self._inner = inner
        self._observability = observability

    @classmethod
    def wrap(cls, inner: Client, observability: ObservabilityFacade) -> Client:
        """Wrap ``inner`` once. Wrapping an already-wrapped client returns it unchanged."""
        if isinstance(inner, cls):
            return inner
        return cls(inner, observability)

    def _prepare_context(self, context: ClientCallContext | None) -> ClientCallContext:
        """Merge the current trace context into a copy of the caller's service parameters."""
        merged_parameters: dict[str, str] = (
            dict(context.service_parameters or {}) if context else {}
        )
        inject_trace_context(merged_parameters)
        if context is None:
            return ClientCallContext(service_parameters=merged_parameters)
        return context.model_copy(update={"service_parameters": merged_parameters})

    async def _call[T](
        self,
        operation: str,
        context: ClientCallContext | None,
        invoke: Callable[[ClientCallContext], Awaitable[T]],
    ) -> T:
        # Context is prepared (and trace context injected) inside `bound`, which `_run_traced`
        # only calls once this operation's own span is active - injecting beforehand would
        # capture the caller's ambient context instead of this call's own span.
        async def bound() -> T:
            return await invoke(self._prepare_context(context))

        return await _run_traced(
            self._observability, "a2a.client." + operation, SpanKind.CLIENT, bound
        )

    def _stream[T](
        self,
        operation: str,
        context: ClientCallContext | None,
        invoke: Callable[[ClientCallContext], AsyncIterator[T]],
    ) -> AsyncGenerator[T]:
        def bound() -> AsyncIterator[T]:
            return invoke(self._prepare_context(context))

        return _stream_traced(
            self._observability,
            "a2a.client." + operation,
            SpanKind.CLIENT,
            bound,
            ambient=nullcontext(),
        )

    def send_message(
        self, request: SendMessageRequest, *, context: ClientCallContext | None = None
    ) -> AsyncIterator[StreamResponse]:
        """Send a message, injecting the current trace context and tracing the call.

        Returns the traced generator directly (no extra wrapping layer), so closing it - via
        exhaustion, an explicit ``aclose()``, or cancellation - propagates straight through to
        the single inner iterator this call owns; see the module docstring's cleanup policy.
        """
        return self._stream(
            "send_message", context, lambda ctx: self._inner.send_message(request, context=ctx)
        )

    def subscribe(
        self, request: SubscribeToTaskRequest, *, context: ClientCallContext | None = None
    ) -> AsyncIterator[StreamResponse]:
        """Subscribe to task updates, injecting the current trace context and tracing the call."""
        return self._stream(
            "subscribe", context, lambda ctx: self._inner.subscribe(request, context=ctx)
        )

    async def get_task(
        self, request: GetTaskRequest, *, context: ClientCallContext | None = None
    ) -> Task:
        """Fetch a task, injecting the current trace context and tracing the call."""
        return await self._call(
            "get_task", context, lambda ctx: self._inner.get_task(request, context=ctx)
        )

    async def cancel_task(
        self, request: CancelTaskRequest, *, context: ClientCallContext | None = None
    ) -> Task:
        """Cancel a task, injecting the current trace context and tracing the call."""
        return await self._call(
            "cancel_task", context, lambda ctx: self._inner.cancel_task(request, context=ctx)
        )

    async def list_tasks(
        self, request: ListTasksRequest, *, context: ClientCallContext | None = None
    ) -> ListTasksResponse:
        """List tasks, injecting the current trace context and tracing the call."""
        return await self._call(
            "list_tasks", context, lambda ctx: self._inner.list_tasks(request, context=ctx)
        )

    async def get_task_push_notification_config(
        self,
        request: GetTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> TaskPushNotificationConfig:
        """Fetch a push-notification config, injecting the current trace context."""
        return await self._call(
            "get_task_push_notification_config",
            context,
            lambda ctx: self._inner.get_task_push_notification_config(request, context=ctx),
        )

    async def create_task_push_notification_config(
        self, request: TaskPushNotificationConfig, *, context: ClientCallContext | None = None
    ) -> TaskPushNotificationConfig:
        """Create a push-notification config, injecting the current trace context."""
        return await self._call(
            "create_task_push_notification_config",
            context,
            lambda ctx: self._inner.create_task_push_notification_config(request, context=ctx),
        )

    async def list_task_push_notification_configs(
        self,
        request: ListTaskPushNotificationConfigsRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> ListTaskPushNotificationConfigsResponse:
        """List push-notification configs, injecting the current trace context."""
        return await self._call(
            "list_task_push_notification_configs",
            context,
            lambda ctx: self._inner.list_task_push_notification_configs(request, context=ctx),
        )

    async def delete_task_push_notification_config(
        self,
        request: DeleteTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> None:
        """Delete a push-notification config, injecting the current trace context."""
        await self._call(
            "delete_task_push_notification_config",
            context,
            lambda ctx: self._inner.delete_task_push_notification_config(request, context=ctx),
        )

    async def get_extended_agent_card(
        self,
        request: GetExtendedAgentCardRequest,
        *,
        context: ClientCallContext | None = None,
        signature_verifier: Callable[[AgentCard], None] | None = None,
    ) -> AgentCard:
        """Fetch the extended agent card, injecting the current trace context."""
        return await self._call(
            "get_extended_agent_card",
            context,
            lambda ctx: self._inner.get_extended_agent_card(
                request, context=ctx, signature_verifier=signature_verifier
            ),
        )

    async def close(self) -> None:
        """Close the wrapped client. Not traced: there is no request/response to correlate."""
        await self._inner.close()


class TracingRequestHandler(RequestHandler):
    """Wraps a concrete A2A ``RequestHandler``, adding spans, W3C extraction, and structured events.

    Every abstract ``RequestHandler`` method is delegated to the wrapped instance. The inbound W3C
    trace context is read from ``ServerCallContext.state['headers']`` (populated by the SDK's
    ``DefaultServerCallContextBuilder`` for the JSON-RPC and REST transports) and made current for
    the duration of the call, so any span the wrapped handler's agent executor starts becomes a
    child of the caller's span.
    """

    def __init__(self, inner: RequestHandler, observability: ObservabilityFacade) -> None:
        """Wrap ``inner`` directly; prefer :meth:`wrap` to avoid double-instrumenting."""
        self._inner = inner
        self._observability = observability

    @classmethod
    def wrap(cls, inner: RequestHandler, observability: ObservabilityFacade) -> RequestHandler:
        """Wrap ``inner`` once. Wrapping an already-wrapped handler returns it unchanged."""
        if isinstance(inner, cls):
            return inner
        return cls(inner, observability)

    @staticmethod
    def _extract_headers(context: ServerCallContext) -> Mapping[str, str]:
        """Read inbound headers from untrusted context state, keeping only string entries."""
        raw = context.state.get("headers")
        if not isinstance(raw, Mapping):
            return {}
        return {
            key: value
            for key, value in raw.items()
            if isinstance(key, str) and isinstance(value, str)
        }

    async def _call[T](
        self, operation: str, context: ServerCallContext, invoke: Callable[[], Awaitable[T]]
    ) -> T:
        with continue_trace(self._extract_headers(context)):
            return await _run_traced(
                self._observability, "a2a.server." + operation, SpanKind.SERVER, invoke
            )

    def _stream[T](
        self,
        operation: str,
        context: ServerCallContext,
        invoke: Callable[[], AsyncIterator[T]],
    ) -> AsyncGenerator[T]:
        # The extracted context manager is entered inside `_stream_traced`, around the whole
        # generator, not here - entering it in this (non-generator) method would attach it only
        # for the instant this call executes, not for the operation's actual lifetime.
        ambient = continue_trace(self._extract_headers(context))
        return _stream_traced(
            self._observability, "a2a.server." + operation, SpanKind.SERVER, invoke, ambient=ambient
        )

    async def on_message_send(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> Task | Message:
        """Handle 'message/send', extracting the caller's trace context and tracing the call."""
        return await self._call(
            "on_message_send", context, lambda: self._inner.on_message_send(params, context)
        )

    def on_message_send_stream(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> AsyncGenerator[_ServerEvent]:
        """Handle streaming 'message/send', extracting the caller's trace context."""
        return self._stream(
            "on_message_send_stream",
            context,
            lambda: self._inner.on_message_send_stream(params, context),
        )

    async def on_get_task(self, params: GetTaskRequest, context: ServerCallContext) -> Task | None:
        """Handle 'tasks/get', extracting the caller's trace context and tracing the call."""
        return await self._call(
            "on_get_task", context, lambda: self._inner.on_get_task(params, context)
        )

    async def on_cancel_task(
        self, params: CancelTaskRequest, context: ServerCallContext
    ) -> Task | None:
        """Handle 'tasks/cancel', extracting the caller's trace context and tracing the call."""
        return await self._call(
            "on_cancel_task", context, lambda: self._inner.on_cancel_task(params, context)
        )

    async def on_list_tasks(
        self, params: ListTasksRequest, context: ServerCallContext
    ) -> ListTasksResponse:
        """Handle 'tasks/list', extracting the caller's trace context and tracing the call."""
        return await self._call(
            "on_list_tasks", context, lambda: self._inner.on_list_tasks(params, context)
        )

    def on_subscribe_to_task(
        self, params: SubscribeToTaskRequest, context: ServerCallContext
    ) -> AsyncGenerator[_ServerEvent]:
        """Handle 'tasks/subscribe', extracting the caller's trace context."""
        return self._stream(
            "on_subscribe_to_task",
            context,
            lambda: self._inner.on_subscribe_to_task(params, context),
        )

    async def on_get_extended_agent_card(
        self, params: GetExtendedAgentCardRequest, context: ServerCallContext
    ) -> AgentCard:
        """Handle the extended agent card request, extracting the caller's trace context."""
        return await self._call(
            "on_get_extended_agent_card",
            context,
            lambda: self._inner.on_get_extended_agent_card(params, context),
        )

    async def on_get_task_push_notification_config(
        self, params: GetTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        """Handle fetching a push-notification config, extracting the caller's trace context."""
        return await self._call(
            "on_get_task_push_notification_config",
            context,
            lambda: self._inner.on_get_task_push_notification_config(params, context),
        )

    async def on_create_task_push_notification_config(
        self, params: TaskPushNotificationConfig, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        """Handle creating a push-notification config, extracting the caller's trace context."""
        return await self._call(
            "on_create_task_push_notification_config",
            context,
            lambda: self._inner.on_create_task_push_notification_config(params, context),
        )

    async def on_delete_task_push_notification_config(
        self, params: DeleteTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> None:
        """Handle deleting a push-notification config, extracting the caller's trace context."""
        await self._call(
            "on_delete_task_push_notification_config",
            context,
            lambda: self._inner.on_delete_task_push_notification_config(params, context),
        )

    async def on_list_task_push_notification_configs(
        self, params: ListTaskPushNotificationConfigsRequest, context: ServerCallContext
    ) -> ListTaskPushNotificationConfigsResponse:
        """Handle listing push-notification configs, extracting the caller's trace context."""
        return await self._call(
            "on_list_task_push_notification_configs",
            context,
            lambda: self._inner.on_list_task_push_notification_configs(params, context),
        )
