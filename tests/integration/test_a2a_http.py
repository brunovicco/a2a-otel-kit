import asyncio
from typing import cast

import httpx
import pytest
from a2a.server.context import ServerCallContext
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.types.a2a_pb2 import GetTaskRequest, Task
from opentelemetry.trace import SpanKind
from starlette.applications import Starlette

from a2a_otel_kit.adapters.a2a import TracingRequestHandler
from a2a_otel_kit.adapters.mcp import ASGIApp
from tests.integration.conftest import TracedObservability, run_asgi_server
from tests.unit.test_a2a_adapter import _FakeRequestHandler


class _TaskHandler(_FakeRequestHandler):
    """Adapt the shared fake to echo the route's requested task identifier."""

    async def on_get_task(self, params: GetTaskRequest, context: ServerCallContext) -> Task | None:
        del context
        return Task(id=params.id)


@pytest.mark.integration
def test_official_a2a_jsonrpc_server_continues_remote_trace_over_tcp(
    traced_observability: TracedObservability,
) -> None:
    """The official Starlette route reaches the traced handler over a real TCP socket."""
    observability = traced_observability.observability
    handler = TracingRequestHandler.wrap(_TaskHandler(), observability)
    app = Starlette(routes=create_jsonrpc_routes(handler, "/"))
    trace_id = "1234567890abcdef1234567890abcdef"
    parent_id = "1234567890abcdef"

    async def request(url: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=5) as client:
            return await client.post(
                url + "/",
                headers={
                    "A2A-Version": "1.0",
                    "traceparent": f"00-{trace_id}-{parent_id}-01",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": "integration-1",
                    "method": "GetTask",
                    "params": {"id": "task-123"},
                },
            )

    with run_asgi_server(cast(ASGIApp, app)) as url:
        response = asyncio.run(request(url))
    assert response.status_code == 200
    assert response.json()["result"]["id"] == "task-123"
    assert observability.flush()

    spans = traced_observability.exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "a2a.server.on_get_task"
    assert spans[0].kind is SpanKind.SERVER
    assert f"{spans[0].context.trace_id:032x}" == trace_id
    assert spans[0].parent is not None
    assert f"{spans[0].parent.span_id:016x}" == parent_id
