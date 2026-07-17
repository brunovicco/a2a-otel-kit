# Architecture

## Purpose and boundary

`a2a-otel-kit` is a Python library that adds vendor-neutral observability to agent-to-agent
applications and MCP services. It owns no agent business logic and runs no standalone service.
Consumers explicitly compose its facade and optional adapters into their process.

The library emits privacy-safe structured events, creates OpenTelemetry spans, and propagates W3C
Trace Context. OTLP export stops at an OpenTelemetry Collector boundary; vendor routing and
credentials belong to the consuming deployment, not this package.

## Layers

```text
src/a2a_otel_kit/
├── domain/        # telemetry vocabulary, sanitization, and domain errors
├── application/   # settings and consumer-facing ports
├── adapters/      # OpenTelemetry, W3C, A2A, and MCP implementations
└── entrypoints/   # explicit composition facade and logging setup
```

### Domain

The domain defines the safe telemetry vocabulary: allowlisted attributes, sensitive-key
rejection, bounded scalar values, structured-event outcomes, and domain errors. It imports no
OpenTelemetry, Pydantic, A2A, MCP, HTTP, or logging framework types.

### Application

The application layer validates immutable observability settings and defines the lifecycle and
facade protocols used by adapters. It describes what the library needs without choosing an SDK,
transport, or exporter implementation.

### Adapters

Adapters implement infrastructure boundaries:

- `tracing.py` builds an isolated OpenTelemetry provider and OTLP/HTTP exporter.
- `propagation.py` injects and extracts W3C context through plain string mappings.
- `a2a.py` wraps the official A2A client and HTTP request-handler contracts.
- `mcp.py` wraps HTTPX and ASGI public boundaries for MCP Streamable HTTP.

The A2A and MCP adapters are optional imports. Installing the base package does not import or
require either SDK. Adapters record fixed operation metadata only; protocol payloads, headers,
URLs, exception messages, prompts, and results are not telemetry attributes.

### Entrypoints

`Observability` is the composition root exposed to consumers. It wires validated settings,
structured logging, sanitization, tracing, flush, and shutdown. `configure_logging()` configures
stdout/stderr output and injects correlation identifiers from the active span. Importing the
package performs no I/O and does not mutate global OpenTelemetry provider state.

## Dependency rule

```text
entrypoints -> application -> domain
adapters    -> application/domain
domain      -> no outer layer
```

`scripts/validate_architecture.py` enforces this direction, prohibits relative imports, and keeps
the optional SDKs outside the inner layers.

## Runtime flows

### Outbound call

```text
consumer -> tracing adapter -> operation span -> W3C injection -> A2A/MCP SDK -> remote peer
```

The adapter starts the operation span before injecting context, so the propagated parent is the
operation span itself. Success, failure, cancellation, and streaming cleanup all unwind the span
and context deterministically.

### Inbound call

```text
remote peer -> A2A route / MCP ASGI app -> W3C extraction -> SERVER span -> wrapped handler
```

Only `traceparent` and `tracestate` are extracted. Invalid or absent context safely starts a new
trace. A2A continuity is implemented for JSON-RPC/REST HTTP; MCP continuity is implemented for
Streamable HTTP.

### Export

```text
library -> OTLP/HTTP -> OpenTelemetry Collector -> deployment-owned backends
```

Each `Observability` instance owns an independent provider and an explicit, idempotent
flush/shutdown lifecycle.

## Verification boundaries

- Unit tests cover sanitization, lifecycle, correlation, concurrency, cancellation, streaming,
  privacy, and workflow security without network I/O.
- Loopback integration tests exercise the official A2A HTTP routes and FastMCP Streamable HTTP
  over real TCP sockets.
- The Collector integration is opt-in because it requires external infrastructure. It verifies
  positive receipt by finding the emitted span in a Collector file-exporter output, rather than
  treating endpoint reachability as success.
- CI tests the minimum supported A2A/MCP SDK versions and the newest releases inside the declared
  upper bounds on Python 3.13 and 3.14.

## Deliberate exclusions

- A2A gRPC context continuity, MCP stdio, and legacy MCP SSE are not supported.
- Collector deployment and retention are outside this library's scope.
- The repository `Dockerfile` is a build/smoke artifact for the library; there is no application
  entrypoint to run.

Material decisions are recorded in `docs/adr/`.
