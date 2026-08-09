# MCP Streamable HTTP integration

`a2a-otel-kit` instruments the public Streamable HTTP boundaries of the official MCP Python SDK.
The integration creates fixed-name client and server spans, propagates W3C Trace Context, and
emits sanitized lifecycle events without inspecting MCP messages.

## Compatibility

- Python: `>=3.13,<3.15`
- MCP Python SDK: `>=2.0,<3`
- Client transport: `httpx2`
- Server boundary: ASGI
- Supported MCP transport: Streamable HTTP

Install the optional integration:

```bash
uv add "a2a-otel-kit[mcp]"
```

## Instrument an MCP client

Wrap the `httpx2.AsyncBaseTransport` before constructing the client passed to
`streamable_http_client`:

```python
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from a2a_otel_kit.adapters.mcp import TracingAsyncTransport
from a2a_otel_kit.entrypoints.observability import Observability


async def call_mcp(url: str, observability: Observability) -> None:
    transport = TracingAsyncTransport.wrap(
        httpx2.AsyncHTTPTransport(),
        observability,
    )

    async with (
        httpx2.AsyncClient(transport=transport, timeout=5) as http_client,
        streamable_http_client(url, http_client=http_client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        await session.list_tools()
```

`TracingAsyncTransport.wrap()` is idempotent. The returned transport delegates closing to the
wrapped transport through the owning `httpx2.AsyncClient` lifecycle.

## Instrument an MCPServer

Wrap the ASGI application returned by `MCPServer.streamable_http_app()`:

```python
from typing import cast

from mcp.server import MCPServer

from a2a_otel_kit.adapters.mcp import ASGIApp, TracingASGIMiddleware
from a2a_otel_kit.entrypoints.observability import Observability


def instrument_server(mcp_server: MCPServer, observability: Observability) -> ASGIApp:
    app = cast(
        ASGIApp,
        mcp_server.streamable_http_app(stateless_http=True, json_response=True),
    )
    return TracingASGIMiddleware.wrap(app, observability)
```

`TracingASGIMiddleware.wrap()` is also idempotent. Keep the returned wrapper at the outer HTTP
boundary so inbound context is active when MCPServer handles the request.

## Telemetry and privacy boundary

The adapter:

- propagates only `traceparent` and `tracestate`;
- creates the fixed operations `mcp.client.streamable_http` and `mcp.server.streamable_http`;
- classifies success or failure from transport outcomes and HTTP status;
- never reads request or response bodies;
- never records MCP arguments, results, prompts, resources, arbitrary headers, URLs, baggage,
  authorization values, or exception text.

Trace context is a correlation mechanism, not an authentication or authorization mechanism. The
consumer remains responsible for TLS, credentials, access control, request limits, and MCP
authorization policy.

## Disabled mode and lifecycle

When observability is disabled, the wrappers continue delegating to the underlying client or ASGI
application without exporting telemetry. Stale partial W3C headers are removed rather than
forwarded as an incoherent pair.

The consuming process owns `Observability.flush()` and `Observability.shutdown()`. Call them from
the application shutdown path after MCP traffic has stopped.

## Verification

Run the MCP adapter unit and real TCP loopback integration tests:

```bash
uv run pytest --no-cov tests/unit/test_mcp_adapter.py
uv run pytest --no-cov -m integration tests/integration/test_mcp_streamable_http.py
```

The loopback test uses the official `ClientSession`, `streamable_http_client`, and MCPServer ASGI
application and requires positive parent/child trace continuity evidence.

## Limitations

- Stdio and legacy SSE do not carry trace context through this adapter.
- The adapter does not add MCP message-level spans or content capture.
- Automatic framework instrumentation can create duplicate lower-level spans; avoid enabling a
  second HTTPX2 or ASGI instrumentation layer for the same boundary.

## Migrating from `a2a-otel-kit` 0.5.x

The 0.5.x line supports MCP SDK 1.x through `httpx`. The next minor line supports MCP SDK 2.x
through `httpx2` and keeps the public `TracingAsyncTransport` name. Replace `httpx` transport and
client objects in MCP integration code with their `httpx2` equivalents. No consumer-side casts or
duck-typed transport workarounds are required.

See [ADR-0007](adr/0007-mcp-sdk-v2-httpx2-boundary.md) for the compatibility decision and
[Privacy](PRIVACY.md) for the package-wide telemetry policy.
