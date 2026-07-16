# a2a-otel-kit

A small, typed Python 3.13 library that standardizes OpenTelemetry initialization, W3C
trace-context propagation, structured JSON logging, and privacy-safe telemetry attributes for A2A
agents and MCP services. It is the reusable observability foundation extracted from the
`multi-agent-credit-desk` project so that it can be pip-installed independently and versioned
across multiple services.

## Scope

This library provides:

- Immutable, validated observability settings (`ObservabilitySettings`).
- Explicit tracing + structured-logging initialization and idempotent shutdown/flush
  (`Observability`).
- W3C `traceparent`/`tracestate` injection into, and extraction from, plain
  `Mapping`/`MutableMapping[str, str]` carriers - the same shape as HTTP headers, gRPC metadata,
  or message-queue headers.
- Deterministic, allowlist-based sanitization of telemetry attributes (`sanitize_attributes`).
- A versioned structured-event schema (`StructuredEvent`, `schema_version`, `event_name`,
  `event_outcome`).
- An optional, concrete OpenTelemetry integration for the official A2A Python SDK
  (`adapters/a2a.py`, requires the `a2a` extra) - see [A2A integration](#a2a-integration).
- Optional Streamable HTTP instrumentation for the official MCP Python SDK
  (`adapters/mcp.py`, requires the `mcp` extra) - see [MCP integration](#mcp-integration).

This library **emits standard OTLP over HTTP and nothing else**. It does not deploy, configure,
or depend on an OTel Collector, Datadog, or Langfuse - those are operated by whatever process
consumes this library (see [Limitations](#limitations-and-deferred-work)). No vendor SDK is
imported here.

## Architecture

```text
src/a2a_otel_kit/
├── domain/         # sanitize_attributes(), StructuredEvent - pure Python, no OTel/pydantic import
├── application/     # ObservabilitySettings, TracerLifecycle/ObservabilityFacade ports
├── adapters/        # OpenTelemetry SDK wiring (tracing.py), W3C propagation (propagation.py),
│                    # optional A2A SDK integration (a2a.py, requires the `a2a` extra)
└── entrypoints/      # configure_logging(), the Observability composition root/facade
```

Dependency direction: `entrypoints -> application -> domain`, `adapters -> application/domain`.
See `docs/ARCHITECTURE.md` for the full rule set this repository enforces.

## Installation

```bash
uv add a2a-otel-kit
```

## Configuration

`ObservabilitySettings` is a frozen `pydantic-settings` model. Construct it explicitly, or load it
from `A2A_OTEL_`-prefixed environment variables (a library-specific prefix - this does not
implement the official OTel SDK auto-instrumentation environment contract):

| Field | Env var | Default | Notes |
|---|---|---|---|
| `service_name` | `A2A_OTEL_SERVICE_NAME` | required | Non-empty |
| `service_version` | `A2A_OTEL_SERVICE_VERSION` | required | Non-empty |
| `environment` | `A2A_OTEL_ENVIRONMENT` | required | Non-empty |
| `enabled` | `A2A_OTEL_ENABLED` | `False` | No-op tracing when `False` |
| `otlp_endpoint` | `A2A_OTEL_OTLP_ENDPOINT` | `None` | Required (`http://`/`https://`) when `enabled=True` |
| `otlp_timeout_seconds` | `A2A_OTEL_OTLP_TIMEOUT_SECONDS` | `10.0` | Must be positive |
| `log_level` | `A2A_OTEL_LOG_LEVEL` | `"INFO"` | Standard `logging` level name |
| `log_format` | `A2A_OTEL_LOG_FORMAT` | `"json"` | `"json"` or `"console"` |

Validation runs at construction time, before any tracer provider or exporter is built. Enabling
tracing without an endpoint raises `InvalidObservabilityConfigurationError` immediately.
`ObservabilitySettings` carries no credential or secret field, so its default `repr()` is always
safe to log.

```python
from a2a_otel_kit import Observability, ObservabilitySettings

settings = ObservabilitySettings(
    service_name="cadastral-agent",
    service_version="0.1.0",
    environment="local",
    enabled=True,
    otlp_endpoint="http://localhost:4318",  # a local OTel Collector, not a vendor endpoint
)
observability = Observability.configure(settings)
```

Leaving `enabled=False` (the default) keeps the process fully untraced: `Observability.configure()`
never requires exporter configuration in that mode.

## Lifecycle

```python
observability = Observability.configure(settings)
try:
    ...
finally:
    observability.flush()      # block until pending spans are exported
    observability.shutdown()   # release exporter resources; safe to call more than once
```

Each `Observability.configure()` call builds an independent instance with no shared global
OpenTelemetry state (no `set_tracer_provider`/`set_global_textmap` call). Repeated initialization
never raises and never corrupts a previously configured instance; when replacing an active
instance, shut the old one down first to release its resources. See `docs/adr/0002-*.md` for the
reasoning behind this choice.

## Tracing and structured events

```python
with observability.start_span("cadastral.lookup", attributes={"operation": "kyc_check"}) as span:
    observability.emit_event("cadastral.lookup.completed", "success", operation="kyc_check")
```

`start_span` produces a no-op, non-recording span when observability is disabled - callers never
need to branch on whether tracing is enabled. `emit_event` writes one structured JSON log line
carrying `schema_version`, `event_name`, and `event_outcome`, and automatically attaches
`trace_id`/`span_id` when called inside an active span. Attributes passed to either call go
through the same allowlist-and-redact sanitizer (see [Privacy guarantees](#privacy-guarantees)).

## Propagation

```python
from a2a_otel_kit import continue_trace, extract_trace_context, inject_trace_context

# Sending side (e.g. a future A2A task hand-off or MCP call):
carrier: dict[str, str] = {}
inject_trace_context(carrier)
# ... send `carrier` alongside the request, e.g. as HTTP headers ...

# Receiving side:
with continue_trace(carrier):
    with observability.start_span("financeiro.cashflow_analysis"):
        ...  # this span is a child of the sender's span
```

`inject_trace_context`/`extract_trace_context`/`continue_trace` operate on plain
`Mapping`/`MutableMapping[str, str]` carriers and never mutate OpenTelemetry's global propagator
registry, so a future HTTP, gRPC, or queue-header adapter can reuse them directly.

## A2A integration

Optional: requires the `a2a` extra.

```bash
uv add "a2a-otel-kit[a2a]"
```

Verified against `a2a-sdk` 1.1.1. Supported extension points:

- **Client (outbound):** `a2a.client.client.Client` - `TracingClient` wraps a concrete client
  instance and delegates every method, injecting the current W3C trace context into
  `ClientCallContext.service_parameters` (the field the SDK's own `get_http_args()` copies into
  outbound HTTP headers for the JSON-RPC and REST transports).
- **Server (inbound, JSON-RPC/REST only):** `a2a.server.request_handlers.request_handler.RequestHandler` -
  `TracingRequestHandler` wraps a concrete handler and extracts a W3C trace context from
  `ServerCallContext.state['headers']` (populated with the real inbound HTTP headers by the SDK's
  `DefaultServerCallContextBuilder`).

```python
# Outbound (a service calling another agent):
from a2a_otel_kit.adapters.a2a import TracingClient

client = TracingClient.wrap(real_client, observability)  # real_client: a2a.client.client.Client
async for event in client.send_message(request):
    ...  # traceparent/tracestate are already injected into the outbound call

# Inbound (an agent's own A2A server):
from a2a_otel_kit.adapters.a2a import TracingRequestHandler

request_handler = TracingRequestHandler.wrap(real_handler, observability)  # wraps e.g. DefaultRequestHandler
# pass request_handler to the FastAPI app builder as usual; the caller's trace context is
# extracted automatically before each method runs.
```

`TracingClient.wrap()`/`TracingRequestHandler.wrap()` are idempotent: wrapping an already-wrapped
instance returns it unchanged, so calling `wrap()` more than once never produces duplicate spans.

**Captured:** a fixed, low-cardinality span name per operation (e.g. `"a2a.client.send_message"`,
built from the SDK's own method name, never from remote-supplied data), one `operation` attribute
(the same fixed name), and a `started`/`completed`/`failed` structured event per operation, all
three sharing the operation's own `trace_id`/`span_id`. Outbound (`TracingClient`) spans use
`SpanKind.CLIENT`; inbound (`TracingRequestHandler`) spans use `SpanKind.SERVER`. A failed
operation's span gets an ERROR status with no description; the original exception or cancellation
always propagates to the caller unchanged.

**Streaming cleanup and terminal outcomes:** `send_message`, `subscribe`, `on_message_send_stream`,
and `on_subscribe_to_task` each own exactly one inner iterator and close it deterministically -
via exhaustion, an exception, an explicit `aclose()`, or task cancellation alike - never relying
on garbage collection. Exactly one terminal event is ever emitted per operation: full stream
exhaustion is `completed`/SUCCESS; anything else (an exception, an early `aclose()`, or
cancellation) is `failed`/ERROR. See `docs/adr/0003-a2a-request-response-wrapping.md` for the full
rationale, including why the SDK's own SSE reader independently arrived at the same
explicit-ownership approach for its underlying HTTP connection.

**Explicitly excluded:** message bodies, task/artifact content, agent names, URLs, header values,
and exception messages are never recorded in a span or event - a failure is signaled by status and
event outcome alone.

**Not covered:** the gRPC transport builds its `ServerCallContext` from gRPC servicer context, not
Starlette headers, so inbound trace-context extraction is unverified for gRPC-originated requests
(wrapping a gRPC-backed handler still produces spans/events; only continuity across that specific
transport boundary is unverified). See `docs/adr/0003-a2a-request-response-wrapping.md` for why
the SDK's own `ClientCallInterceptor` hook was not used for span lifetime.

## MCP integration

Optional: `uv add "a2a-otel-kit[mcp]"`. Verified against `mcp` 1.28.1 and limited to public
Streamable HTTP boundaries. Wrap an HTTPX transport and pass its client to
`streamable_http_client(http_client=client)`; wrap the ASGI app returned by
`FastMCP.streamable_http_app()` on the server:

```python
import httpx
from mcp.client.streamable_http import streamable_http_client

from a2a_otel_kit.adapters.mcp import TracingASGIMiddleware, TracingAsyncTransport

transport = TracingAsyncTransport.wrap(httpx.AsyncHTTPTransport(), observability)
mcp_asgi_app = TracingASGIMiddleware.wrap(fastmcp.streamable_http_app(), observability)

async with httpx.AsyncClient(transport=transport) as http_client:
    async with streamable_http_client(url, http_client=http_client) as streams:
        ...  # use the MCP session while both contexts own their resources
```

Outbound spans use `SpanKind.CLIENT`; inbound spans use `SpanKind.SERVER`. Only fixed operation
names and the fixed `operation` attribute are recorded. The adapter propagates only `traceparent`
and `tracestate`; it never reads MCP arguments, results, request/response bodies, arbitrary header
values, URLs, or exception text. Setup is explicit and both `wrap()` methods are idempotent.
HTTP 2xx/3xx responses complete successfully; HTTP 4xx/5xx responses produce an ERROR span and
one `failed` event without reading the response body or recording the status response content.
Stdio and legacy SSE transports are not supported. See ADR-0004.

## Privacy guarantees

- Telemetry attributes are **deny-by-default**: `sanitize_attributes()` keeps only allowlisted
  keys (see `DEFAULT_ALLOWED_ATTRIBUTE_KEYS` in `domain/attributes.py`), rejects any key that
  looks like a credential or secret (password, token, authorization, cookie, api-key, credential,
  private-key, ssn, access-key patterns) even if the caller adds it to the allowlist, and drops
  non-scalar or oversized string values.
- There is no prompt/completion/content-capture concept anywhere in this library's public API.
  Metadata is all it ever sends - full stop, not "off by default."
- `ObservabilitySettings` has no secret-bearing field, so its representation is always safe to
  print or log; a future field named like a credential would need its own redaction and is
  guarded by a repository test (`tests/unit/test_settings.py`).
- Structured logs never carry request/response payloads, only the fields a caller explicitly
  passes through `emit_event`/`start_span`, filtered by the same allowlist.

The **boundary** this library draws: telemetry (traces, structured logs) is metadata-only by
construction here. Anything resembling artifact/content capture (prompts, documents, customer
data) belongs in an application-owned artifact store, never in telemetry - this library provides
no path to do otherwise.

## Limitations and deferred work

Deliberately out of scope for this library:

- **Other MCP transports.** The optional MCP adapter supports Streamable HTTP only. Stdio and
  legacy SSE do not expose the same HTTP propagation boundary and remain out of scope.
- **gRPC trace-context continuity for A2A.** `TracingRequestHandler` extracts inbound trace
  context from Starlette request headers, which the gRPC transport does not populate the same
  way; gRPC-originated requests still get spans/events, just not verified context continuity.
- **Vendor backends (Datadog, Langfuse).** This library emits OTLP and stops there. Fan-out to
  vendor backends is the responsibility of a central OTel Collector operated outside this
  library - see the sibling `multi-agent-credit-desk` repository's
  `docs/adr/0006-observability-otel-fanout-datadog-langfuse.md`. No Datadog or Langfuse SDK is a
  dependency of this package.
- **Infrastructure.** No OTel Collector config, Docker Compose stack, or deployment manifests
  live in this repository.
- **Custom OTLP authentication headers.** The exporter is constructed with an endpoint and
  timeout only; per-request auth headers for a secured OTLP endpoint are not yet supported. Add
  them at the point they become necessary, with an explicit secret-handling review at that time.

## Development

```bash
uv sync --frozen
uv run pytest
uv run python scripts/quality_gate.py
```

See `AGENTS.md` for the full engineering contract and `docs/ARCHITECTURE.md` for the enforced
dependency rules.
