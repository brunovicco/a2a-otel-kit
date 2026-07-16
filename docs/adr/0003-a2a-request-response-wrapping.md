# ADR-0003: Wrap the A2A `Client`/`RequestHandler` ABCs instead of using `ClientCallInterceptor`

- Status: Accepted
- Date: 2026-07-16

## Context

`a2a-sdk` 1.1.1 ships a documented tracing hook, `a2a.client.interceptors.ClientCallInterceptor`,
whose docstring states it is "ideal for concerns like authentication, logging, or tracing." Using
it was the obvious first choice for the outbound (client) side of this milestone's A2A
integration.

Reading `a2a.client.base_client.BaseClient._execute_with_interceptors` shows the transport call is
not wrapped in a `try`/`except`:

```python
result = await transport_call(before_args.input, before_args.context)
```

If `transport_call` raises, the method returns (via the exception) without ever constructing
`AfterArgs` or calling `interceptor.after()`. A span opened in `before()` and expected to be
closed in `after()` would then never close on any failed call: the span leaks unexported, and -
more seriously - the OpenTelemetry `Context` attached when the span was started is never detached,
corrupting the ambient trace context for the rest of that async task.

## Decision

Do not use `ClientCallInterceptor` for span lifetime. Instead, `TracingClient` and
`TracingRequestHandler` (`src/a2a_otel_kit/adapters/a2a.py`) wrap the whole `Client`/
`RequestHandler` abstract base class, delegating every method through two shared helpers
(`_run_traced`, `_stream_traced`) that hold the span open in a single `try`/`except`/`finally`
this library controls. `ClientCallInterceptor` is not used at all; W3C trace-context injection
happens by merging into `ClientCallContext.service_parameters` directly inside the wrapped call,
after the operation's own span has started (not before - injecting first would capture the
caller's ambient context instead of this call's own span, a bug caught during implementation and
fixed with a smoke test before writing the automated test suite).

This is still an "official extension point," not a monkeypatch: `Client` and `RequestHandler` are
both public abstract base classes explicitly designed to be implemented by alternative backends.

## Consequences

- Every span this library creates for an A2A operation is guaranteed to close, with a correct
  ERROR status, on every code path including transport exceptions - the failure mode that made
  `ClientCallInterceptor` unsafe for this purpose does not apply here.
- The cost is more code: each ABC has 11 abstract methods, so `TracingClient`/
  `TracingRequestHandler` each implement 11 thin, fully-typed delegating methods (2 streaming, 9
  non-streaming) rather than one generic interceptor. `tests/unit/test_a2a_adapter.py` exercises
  every one of them to keep this surface from silently drifting out of sync with a future SDK
  release that adds or renames a method.
- If a future `a2a-sdk` release fixes the `after()`-on-exception gap, `ClientCallInterceptor`
  could become a viable, smaller alternative for injection-only concerns; span lifetime would
  still be safer managed via the wrapping approach here regardless, since it does not depend on
  that guarantee holding.

## Addendum: async-generator ownership and cleanup (streaming operations)

A review of the initial implementation found that the streaming path (`_stream_traced`,
`TracingClient.send_message`/`subscribe`, `TracingRequestHandler.on_message_send_stream`/
`on_subscribe_to_task`) had the same class of bug ADR-0003 was written to avoid, one level down:
a bare `async for item in invoke(): yield item` does not call `aclose()` on the inner iterator
when the *outer* generator is abandoned early. Python's `async for` never closes the iterable it
consumes on `break`, `return`, or an exception unwinding past it - that is the caller's
responsibility, and gets silently skipped when the caller is itself a thin passthrough generator.

The pinned SDK's own code corroborates this failure mode: `a2a.client.transports.http_helpers`
implements its SSE reader (`_SSEEventSource`) as a class with explicit `__aenter__`/`__aexit__`
instead of an `@asynccontextmanager`-decorated generator specifically because, per its docstring,
"an outer async generator... abandoned early... causes the Python event loop to concurrently
throw `GeneratorExit` into the nested context manager's suspended generator," crashing at
finalization. This library's fix is the same idea one layer up: own the iterator explicitly and
close it deterministically rather than trust generator-to-generator delegation.

**Decision:** `_stream_traced` is the *only* generator layer for any streaming operation, in
either direction. Every class-level method that used to wrap it in its own `async for`/`yield`
(`TracingClient.send_message`, `TracingRequestHandler._stream`) now returns the object
`_stream_traced` produces directly, so there is exactly one generator per streaming call between
the consumer and the wrapped SDK object. `_stream_traced` calls `invoke()` exactly once, keeps
the resulting iterator in a local variable, and closes it in a `finally` block using
`getattr(iterator, "aclose", None)` - defensive because the wrapped `Client`/`RequestHandler`
ABCs type their streaming methods as `AsyncIterator`, which does not guarantee `aclose()`, even
though every concrete implementation this adapter has been verified against is in fact an async
generator that has one.

**Terminal-outcome policy:** a stream that is fully exhausted is `completed`/SUCCESS. Anything
else - an exception raised during iteration, an explicit `aclose()` from the consumer, or task
cancellation - is `failed`/ERROR. OpenTelemetry does not mandate a single status for cancellation
or partial consumption, so this is a deliberate, consistent library policy: exactly one terminal
event is ever emitted per operation, and "failed" always means "did not fully complete," with no
third category to reason about. `except BaseException` (not `Exception`) is required for this,
since both `GeneratorExit` (raised by `aclose()`) and `asyncio.CancelledError` subclass
`BaseException`, not `Exception`; both are still re-raised unchanged after cleanup runs - this
adapter never swallows a cancellation or a close signal, only observes it.

The non-streaming path (`_run_traced`) got the matching, simpler fix: `except BaseException`
instead of `except Exception`, so a cancelled non-streaming call also gets a defined `failed`
outcome instead of silently emitting neither terminal event. It needs no iterator-ownership
change, since a single awaited coroutine has no "partial consumption" state to leak - it runs to
completion or unwinds through its `with`/`try` blocks exactly once, either way.

Both `_run_traced` and `_stream_traced` also now emit their `started` event *inside* the
operation's span (previously emitted before the span was entered), so `started`, `completed`,
and `failed` always share the operation's own `trace_id`/`span_id` rather than whatever span
happened to be ambient at call time - and both now take an explicit `kind: SpanKind` parameter
(`CLIENT` for `TracingClient`, `SERVER` for `TracingRequestHandler`) instead of relying on the
default `INTERNAL`.
