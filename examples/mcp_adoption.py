"""Minimal instrumentation helpers for MCP Streamable HTTP client/server boundaries."""

import httpx2

from a2a_otel_kit.adapters.mcp import ASGIApp, TracingASGIMiddleware, TracingAsyncTransport
from a2a_otel_kit.entrypoints.observability import Observability


def instrument_mcp_client(
    transport: httpx2.AsyncBaseTransport, observability: Observability
) -> httpx2.AsyncBaseTransport:
    """Wrap the HTTPX2 transport passed to ``streamable_http_client``."""
    return TracingAsyncTransport.wrap(transport, observability)


def instrument_mcp_server(app: ASGIApp, observability: Observability) -> ASGIApp:
    """Wrap the ASGI app returned by ``MCPServer.streamable_http_app()``."""
    return TracingASGIMiddleware.wrap(app, observability)
