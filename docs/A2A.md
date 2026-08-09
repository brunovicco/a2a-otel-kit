# A2A integration

The optional A2A adapter adds OpenTelemetry spans and W3C Trace Context propagation around public boundaries of the official A2A Python SDK.

Install it with:

```bash
uv add "a2a-otel-kit[a2a]"
```

Supported SDK range:

```text
a2a-sdk >=1.1,<2.0
```

CI exercises the minimum supported resolution and the newest bounded resolution.

## Design goals

The adapter is designed to preserve four properties:

1. A caller and a downstream A2A agent can participate in the same distributed trace.
2. The library records fixed operational metadata rather than protocol or business content.
3. Wrapping is explicit and idempotent.
4. Streaming spans have deterministic lifetime and exactly one terminal outcome.

## Outbound client

Wrap a concrete `a2a.client.client.Client`:

```python
from a2a_otel_kit.adapters.a2a import TracingClient

client = TracingClient.wrap(real_client, observability)

async for event in client.send_message(request):
    ...
```

The wrapper creates a CLIENT span and injects the active W3C context into `ClientCallContext.service_parameters`, which the supported HTTP transports propagate as request headers.

The operation span exists before injection, so the propagated `traceparent` represents the A2A operation itself.

## Inbound request handler

Wrap a concrete `a2a.server.request_handlers.request_handler.RequestHandler`:

```python
from a2a_otel_kit.adapters.a2a import TracingRequestHandler

request_handler = TracingRequestHandler.wrap(
    real_handler,
    observability,
)
```

For JSON-RPC and REST HTTP requests, the wrapper extracts W3C context from inbound headers exposed through `ServerCallContext` and creates a SERVER span.

If context is absent or invalid, the operation safely starts a new trace.

## Recorded telemetry

Each supported operation uses a fixed low-cardinality span name such as:

```text
a2a.client.send_message
```

The adapter records:

- fixed operation name;
- fixed `operation` attribute;
- `started`, `completed`, or `failed` structured event;
- active `trace_id` and `span_id` correlation;
- span status.

It deliberately does **not** record:

- message bodies;
- task content;
- artifact content;
- agent names supplied by a remote peer;
- URLs;
- arbitrary header names or values;
- authorization material;
- exception messages.

The original exception or cancellation is propagated to the caller unchanged.

## Streaming lifecycle

Streaming APIs require careful span ownership because the network operation can outlive the method call that returns an iterator.

The wrapper therefore owns exactly one inner iterator and closes it deterministically.

A stream has exactly one terminal outcome:

| Situation | Outcome |
|---|---|
| Full exhaustion | `completed` / SUCCESS |
| Exception | `failed` / ERROR |
| Task cancellation | `failed` / ERROR |
| Early `aclose()` | `failed` / ERROR |

Cleanup does not rely on garbage collection.

This behavior applies to the streaming operations covered by the adapter, including `send_message`, `subscribe`, `on_message_send_stream`, and `on_subscribe_to_task`.

See the corresponding ADR under [`adr/`](adr/) for the full design rationale.

## Idempotent wrapping

Both wrappers are idempotent:

```python
wrapped = TracingClient.wrap(real_client, observability)
same = TracingClient.wrap(wrapped, observability)

assert same is wrapped
```

This prevents accidental duplicate instrumentation when composition happens in more than one application layer.

## Trace flow

```text
caller
  │
  ├─ CLIENT span: a2a.client.*
  │      │
  │      └─ inject traceparent / tracestate
  │
  ▼
A2A HTTP boundary
  │
  ├─ extract traceparent / tracestate
  │
  └─ SERVER span: a2a.server.*
         │
         ▼
   wrapped handler
```

## gRPC limitation

A2A gRPC uses a different server context path than the HTTP JSON-RPC / REST transports.

Wrapping a handler can still create spans and structured events, but inbound W3C trace-context continuity for gRPC-originated requests is not verified by this project.

Do not represent gRPC continuity as supported until a dedicated adapter and integration test establish that contract.

## Testing

Run the A2A integration test against real loopback HTTP routes:

```bash
uv run pytest --no-cov -m integration \
  tests/integration/test_a2a_http.py
```

The repository also validates cancellation, streaming cleanup, duplicate wrapping, privacy boundaries, and supported SDK versions through its unit/contract suites and CI.

## Related documentation

- [Architecture](ARCHITECTURE.md)
- [Privacy](PRIVACY.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Documentation index](README.md)
