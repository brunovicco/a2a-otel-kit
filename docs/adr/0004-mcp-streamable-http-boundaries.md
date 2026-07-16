# ADR-0004: Instrument MCP at public Streamable HTTP boundaries

## Status

Accepted

## Context

The MCP Python SDK 1.28.1 publicly accepts a caller-provided `httpx.AsyncClient` through
`mcp.client.streamable_http.streamable_http_client(http_client=...)`. `FastMCP` publicly exposes
`streamable_http_app()`, which returns an ASGI application. These boundaries support propagation
and lifecycle-safe tracing without intercepting MCP messages or relying on SDK internals.

## Decision

Provide an idempotent HTTPX `AsyncBaseTransport` wrapper for outbound calls and an idempotent ASGI
middleware wrapper for inbound calls. Support Streamable HTTP only. Propagate only `traceparent`
and `tracestate`; use fixed CLIENT/SERVER span names and the fixed `operation` attribute. Never
read request or response bodies, MCP arguments/results, arbitrary headers, or exception text.

Before outbound injection, both W3C fields are removed case-insensitively and the current
`traceparent`/`tracestate` pair is injected together. This prevents a stale or partial caller
carrier from becoming incoherent. HTTP status is observed without body access: 2xx/3xx is success;
4xx/5xx is ERROR/failed. Inbound middleware observes only the integer `status` in the forwarded
`http.response.start` message and otherwise forwards every ASGI message unchanged.

The outbound span covers transport request dispatch and response-header receipt. HTTPX retains
ownership of response-stream cleanup. The inbound span covers the complete ASGI invocation, so
failure and cancellation always unwind both the span and extracted context. Cancellation is a
failed terminal outcome and is re-raised unchanged.

## Consequences

Consumers explicitly compose the wrappers at the SDK's public boundaries. Stdio, legacy SSE,
and MCP message-level semantics remain out of scope. The adapter depends on the optional `mcp`
extra and does not configure global telemetry.
