import asyncio
from typing import cast

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp import FastMCP
from opentelemetry.trace import SpanKind

from a2a_otel_kit.adapters.mcp import ASGIApp, TracingASGIMiddleware, TracingAsyncTransport
from tests.integration.conftest import TracedObservability, run_asgi_server


@pytest.mark.integration
def test_fastmcp_streamable_http_propagates_context_over_tcp(
    traced_observability: TracedObservability,
) -> None:
    """A real FastMCP session links the client and server spans without exposing content."""
    observability = traced_observability.observability
    fastmcp = FastMCP("integration", stateless_http=True, json_response=True)

    @fastmcp.tool()
    def echo_length(value: str) -> int:
        """Return only the input length."""
        return len(value)

    app = TracingASGIMiddleware.wrap(cast(ASGIApp, fastmcp.streamable_http_app()), observability)

    async def scenario(url: str) -> int:
        transport = TracingAsyncTransport.wrap(httpx.AsyncHTTPTransport(), observability)
        async with (
            httpx.AsyncClient(transport=transport, timeout=5) as client,
            streamable_http_client(url + "/mcp", http_client=client) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "echo_length", {"value": "private-integration-payload"}
            )
            assert not result.isError
            assert result.structuredContent is not None
            return int(result.structuredContent["result"])

    with run_asgi_server(app) as url:
        assert asyncio.run(scenario(url)) == len("private-integration-payload")
    assert observability.flush()

    spans = traced_observability.exporter.get_finished_spans()
    client_spans = [span for span in spans if span.kind is SpanKind.CLIENT]
    server_spans = [span for span in spans if span.kind is SpanKind.SERVER]
    assert client_spans
    assert server_spans
    for server_span in server_spans:
        assert server_span.parent is not None
        assert any(
            client.context.span_id == server_span.parent.span_id
            and client.context.trace_id == server_span.context.trace_id
            for client in client_spans
        )
    assert "private-integration-payload" not in repr(spans)
