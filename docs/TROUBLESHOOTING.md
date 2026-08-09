# Troubleshooting

This guide focuses on the most common integration failures when adopting `a2a-otel-kit`.

## No spans are exported

Check the following in order.

### 1. Is observability enabled?

`enabled=False` intentionally creates no recording spans.

```python
settings = ObservabilitySettings(
    service_name="my-service",
    service_version="1.0.0",
    environment="local",
    enabled=True,
    otlp_endpoint="http://localhost:4318/v1/traces",
)
```

### 2. Is the endpoint an OTLP/HTTP traces endpoint?

For a local Collector, a common endpoint is:

```text
http://localhost:4318/v1/traces
```

The library exports OTLP over HTTP. Confirm that the receiving Collector exposes the corresponding receiver.

### 3. Are pending spans flushed?

Before process exit:

```python
observability.flush()
observability.shutdown()
```

Short-lived scripts can terminate before a batch exporter sends pending spans if lifecycle cleanup is skipped.

### 4. Verify positive receipt

Do not treat an open TCP port or successful `flush()` as proof that the backend received a span.

The repository's Collector integration test verifies positive receipt by checking Collector output for the expected service and span.

Use `compose.collector.yml` and the integration test when isolating export problems.

## Parent and child spans appear as separate traces

Distributed continuity requires context propagation at every boundary.

Check:

- outbound adapter is installed;
- inbound adapter is installed;
- `traceparent` is not stripped by an intermediary;
- the downstream service extracts context before creating its server span;
- no application code starts a detached context between extraction and span creation.

For A2A, HTTP JSON-RPC / REST continuity is supported.

For MCP, Streamable HTTP continuity is supported.

A2A gRPC continuity is not currently a verified contract.

## Duplicate spans

Protocol wrappers are designed to be idempotent.

Prefer:

```python
client = TracingClient.wrap(client, observability)
```

instead of manually layering custom instrumentation around the same protocol boundary.

If duplicate spans remain, inspect application middleware and framework auto-instrumentation. Another OpenTelemetry integration may be instrumenting HTTPX, ASGI, or another lower-level transport in addition to `a2a-otel-kit`.

Decide which layer owns the span vocabulary to avoid duplicate semantic spans.

## A stream reports failure after early close

This is expected.

For supported A2A streaming operations:

- full exhaustion is successful;
- exception is failure;
- cancellation is failure;
- early `aclose()` is failure.

The adapter treats an incomplete stream as a non-successful terminal operation and emits exactly one terminal event.

## HTTP 4xx or 5xx is marked as ERROR in MCP

This is expected.

For MCP Streamable HTTP:

- 2xx and 3xx responses complete successfully;
- 4xx and 5xx responses create an ERROR span and a failed event.

The response body is not read for telemetry and is not recorded.

## I cannot find prompts or MCP arguments in telemetry

That is intentional.

The public telemetry model does not provide prompt/completion capture.

A2A bodies, task/artifact content, MCP arguments/results, authorization values, arbitrary headers, URLs, and exception messages are excluded from protocol telemetry.

If an application needs artifact capture, use an application-owned artifact store with its own access, retention, and governance controls.

## Credentials do not rotate automatically

OTLP authentication headers are resolved during `Observability.configure()`.

Dynamic per-request credential refresh is deliberately unsupported.

To rotate credentials:

1. configure a new `Observability` instance using a provider that resolves the new credential;
2. switch application ownership to the new instance;
3. flush and shut down the previous instance.

## MCP stdio does not propagate tracing

MCP stdio is outside the current adapter boundary.

The implemented MCP integration targets public Streamable HTTP boundaries through HTTPX2 and ASGI.

Do not expect stdio calls to continue W3C HTTP trace context.

## A2A gRPC creates spans but does not continue the caller trace

Inbound gRPC context continuity is not verified.

The current inbound A2A extraction contract is built around HTTP headers surfaced by the supported JSON-RPC / REST server path.

Treat gRPC continuity as unsupported until a dedicated implementation and integration test are added.

## Debugging checklist

When a distributed trace is broken, collect:

```text
service_name
service_version
environment
enabled
otlp_endpoint host/path (without credentials)
protocol: A2A or MCP
transport: JSON-RPC, REST, Streamable HTTP, gRPC, stdio
client wrapper installed?
server wrapper installed?
traceparent present at outbound boundary?
traceparent present at inbound boundary?
flush/shutdown executed?
Collector positive receipt verified?
```

Never paste authorization headers, API keys, cookies, or business payloads into an issue.

## Reporting a problem

Include:

- package version;
- Python version;
- A2A/MCP SDK version when relevant;
- minimal reproduction;
- expected and actual trace topology;
- sanitized logs;
- whether the issue reproduces with the local Collector integration.

Do not include prompts, customer data, credentials, or raw protocol payloads.
