"""A2A Risk Agent that calls the customer-data MCP service."""

from collections.abc import AsyncGenerator
from typing import cast

import httpx2
import uvicorn
from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import Event
from a2a.server.request_handlers.request_handler import RequestHandler
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.types.a2a_pb2 import (
    AgentCard,
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetExtendedAgentCardRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    ListTaskPushNotificationConfigsRequest,
    ListTaskPushNotificationConfigsResponse,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    SendMessageRequest,
    SubscribeToTaskRequest,
    Task,
    TaskPushNotificationConfig,
)
from common import MCP_URL, configure_observability
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette

from a2a_otel_kit.adapters.a2a import TracingRequestHandler
from a2a_otel_kit.adapters.mcp import ASGIApp, TracingAsyncTransport

observability = configure_observability("risk-agent")


async def _lookup_risk_score(customer_id: str) -> int:
    """Read the synthetic customer risk score from the traced MCP service."""
    transport = TracingAsyncTransport.wrap(
        httpx2.AsyncHTTPTransport(),
        observability,
    )

    async with (
        httpx2.AsyncClient(transport=transport, timeout=5) as client,
        streamable_http_client(MCP_URL, http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        result = await session.call_tool(
            "get_customer_risk_score",
            {"customer_id": customer_id},
        )

        if result.is_error or result.structured_content is None:
            raise RuntimeError("MCP risk lookup failed")

        return int(result.structured_content["result"])


class RiskRequestHandler(RequestHandler):
    """Handle the A2A operations required by the local risk demonstration."""

    async def on_get_task(
        self,
        params: GetTaskRequest,
        context: ServerCallContext,
    ) -> Task | None:
        """Look up a risk score and encode the synthetic result as an A2A task."""
        del context
        score = await _lookup_risk_score(params.id)
        return Task(id=f"{params.id}-risk-{score}")

    async def on_message_send(
        self,
        params: SendMessageRequest,
        context: ServerCallContext,
    ) -> Task | Message:
        """Return a synthetic task for the unused message operation."""
        del params, context
        return Task(id="demo-message-task")

    async def on_message_send_stream(
        self,
        params: SendMessageRequest,
        context: ServerCallContext,
    ) -> AsyncGenerator[Event]:
        """Return an empty stream because streaming is outside the demo."""
        del params, context
        return
        yield

    async def on_cancel_task(
        self,
        params: CancelTaskRequest,
        context: ServerCallContext,
    ) -> Task | None:
        """Return a synthetic canceled task for the unused operation."""
        del params, context
        return Task(id="cancelled-demo-task")

    async def on_list_tasks(
        self,
        params: ListTasksRequest,
        context: ServerCallContext,
    ) -> ListTasksResponse:
        """Return an empty task list for the unused operation."""
        del params, context
        return ListTasksResponse()

    async def on_subscribe_to_task(
        self,
        params: SubscribeToTaskRequest,
        context: ServerCallContext,
    ) -> AsyncGenerator[Event]:
        """Return an empty stream because subscriptions are outside the demo."""
        del params, context
        return
        yield

    async def on_get_extended_agent_card(
        self,
        params: GetExtendedAgentCardRequest,
        context: ServerCallContext,
    ) -> AgentCard:
        """Return an empty agent card for the unused operation."""
        del params, context
        return AgentCard()

    async def on_get_task_push_notification_config(
        self,
        params: GetTaskPushNotificationConfigRequest,
        context: ServerCallContext,
    ) -> TaskPushNotificationConfig:
        """Return an empty push configuration for the unused operation."""
        del params, context
        return TaskPushNotificationConfig()

    async def on_create_task_push_notification_config(
        self,
        params: TaskPushNotificationConfig,
        context: ServerCallContext,
    ) -> TaskPushNotificationConfig:
        """Return the input push configuration for the unused operation."""
        del context
        return params

    async def on_delete_task_push_notification_config(
        self,
        params: DeleteTaskPushNotificationConfigRequest,
        context: ServerCallContext,
    ) -> None:
        """Accept push configuration deletion for the unused operation."""
        del params, context

    async def on_list_task_push_notification_configs(
        self,
        params: ListTaskPushNotificationConfigsRequest,
        context: ServerCallContext,
    ) -> ListTaskPushNotificationConfigsResponse:
        """Return an empty push configuration list for the unused operation."""
        del params, context
        return ListTaskPushNotificationConfigsResponse()


handler = TracingRequestHandler.wrap(RiskRequestHandler(), observability)
app = Starlette(routes=create_jsonrpc_routes(handler, "/"))

if __name__ == "__main__":
    try:
        uvicorn.run(
            cast(ASGIApp, app),
            host="127.0.0.1",
            port=8101,
            log_level="warning",
        )
    finally:
        observability.flush()
        observability.shutdown()
