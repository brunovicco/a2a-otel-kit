# ADR-0007: Target MCP SDK 2.x through the native HTTPX2 boundary

## Status

Accepted

## Context

The MCP authentication reference client and server require MCP Python SDK `>=2.0,<3` and the MCP
`2026-07-28` protocol profile. The SDK 2.x client accepts an `httpx2.AsyncClient` at the public
Streamable HTTP boundary, while `a2a-otel-kit` 0.5.x targets MCP SDK 1.x and subclasses
`httpx.AsyncBaseTransport`.

The two transport packages are nominally different even where their runtime protocols look
similar. Depending on duck typing and consumer-side casts would make the public integration
appear supported without a type-safe package contract. Keeping both SDK generations behind one
transport class would also require import-order or runtime-version branching at an adapter
boundary that should remain explicit.

## Decision

- Move the public `mcp` extra and development contract to `mcp>=2.0,<3`.
- Keep the `TracingAsyncTransport` public name, but implement it natively against
  `httpx2.AsyncBaseTransport`, `httpx2.Request`, and `httpx2.Response`.
- Continue using the official `streamable_http_client(http_client=...)` and
  `MCPServer.streamable_http_app()` boundaries only.
- Preserve `TracingASGIMiddleware` as a framework-neutral ASGI wrapper; it does not depend on a
  specific HTTPX generation.
- Preserve the metadata-only policy: propagate only `traceparent` and `tracestate`, use fixed
  low-cardinality operation names, suppress exception recording, and never inspect bodies, MCP
  arguments/results, arbitrary headers, URLs, or exception text.
- Exercise the MCP 2.0.0 floor and the newest compatible 2.x release on Python 3.13 and 3.14.
- End MCP 1.x support in the next minor release. Consumers that require MCP 1.x remain on the
  0.5.x line.

## Consequences

- MCP 2.x consumers no longer need direct `httpx` dependencies or unsafe transport casts to use
  the adapter.
- The optional MCP extra resolves with the authentication reference templates without weakening
  their SDK contract.
- This is a deliberate pre-1.0 compatibility break and requires a minor release with migration
  notes.
- A single installation does not claim simultaneous MCP 1.x and 2.x adapter support. Maintaining
  both would require separate explicitly typed adapters and compatibility matrices, which is not
  justified by the current reference implementations.
