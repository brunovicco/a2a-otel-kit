"""Orchestrator for the end-to-end A2A to MCP trace demo."""

from collections.abc import AsyncIterator, Callable

import httpx
from a2a.client.client import Client, ClientCallContext
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
    SendMessageRequest,
    StreamResponse,
    SubscribeToTaskRequest,
    Task,
    TaskPushNotificationConfig,
)
from common import PRIVATE_CUSTOMER_ID, RISK_AGENT_URL, configure_observability

from a2a_otel_kit.adapters.a2a import TracingClient


class JsonRpcA2AClient(Client):
    """Minimal JSON-RPC A2A client needed by the local demonstration."""

    def __init__(self, base_url: str) -> None:
        """Initialize the client with the Risk Agent base URL."""
        super().__init__()
        self._base_url = base_url

    async def get_task(
        self,
        request: GetTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> Task:
        """Fetch a task from the Risk Agent through A2A JSON-RPC."""
        headers = {
            "A2A-Version": "1.0",
            **dict((context.service_parameters or {}) if context else {}),
        }
        payload = {
            "jsonrpc": "2.0",
            "id": "demo-request-1",
            "method": "GetTask",
            "params": {"id": request.id},
        }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self._base_url}/",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            body = response.json()

        if "error" in body:
            raise RuntimeError(f"A2A JSON-RPC error: {body['error']}")

        return Task(id=str(body["result"]["id"]))

    async def send_message(
        self,
        request: SendMessageRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncIterator[StreamResponse]:
        """Return an empty stream because message sending is outside the demo."""
        del request, context
        return
        yield

    async def subscribe(
        self,
        request: SubscribeToTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncIterator[StreamResponse]:
        """Return an empty stream because subscriptions are outside the demo."""
        del request, context
        return
        yield

    async def cancel_task(
        self,
        request: CancelTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> Task:
        """Return a synthetic canceled task for the unused client operation."""
        del request, context
        return Task(id="cancelled")

    async def list_tasks(
        self,
        request: ListTasksRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> ListTasksResponse:
        """Return an empty task list for the unused client operation."""
        del request, context
        return ListTasksResponse()

    async def get_task_push_notification_config(
        self,
        request: GetTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> TaskPushNotificationConfig:
        """Return an empty push configuration for the unused client operation."""
        del request, context
        return TaskPushNotificationConfig()

    async def create_task_push_notification_config(
        self,
        request: TaskPushNotificationConfig,
        *,
        context: ClientCallContext | None = None,
    ) -> TaskPushNotificationConfig:
        """Return the input configuration for the unused client operation."""
        del context
        return request

    async def list_task_push_notification_configs(
        self,
        request: ListTaskPushNotificationConfigsRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> ListTaskPushNotificationConfigsResponse:
        """Return an empty configuration list for the unused client operation."""
        del request, context
        return ListTaskPushNotificationConfigsResponse()

    async def delete_task_push_notification_config(
        self,
        request: DeleteTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> None:
        """Accept deletion for the unused client operation."""
        del request, context

    async def get_extended_agent_card(
        self,
        request: GetExtendedAgentCardRequest,
        *,
        context: ClientCallContext | None = None,
        signature_verifier: Callable[[AgentCard], None] | None = None,
    ) -> AgentCard:
        """Return an empty agent card for the unused client operation."""
        del request, context, signature_verifier
        return AgentCard()

    async def close(self) -> None:
        """Close the client, which owns no persistent resources."""


async def run() -> str:
    """Run one traced risk assessment and return its trace identifier."""
    observability = configure_observability("orchestrator")
    client = TracingClient.wrap(
        JsonRpcA2AClient(RISK_AGENT_URL),
        observability,
    )

    try:
        with observability.start_span(
            "demo.risk_assessment",
            attributes={"operation": "risk_assessment"},
        ) as span:
            trace_id = f"{span.get_span_context().trace_id:032x}"
            task = await client.get_task(GetTaskRequest(id=PRIVATE_CUSTOMER_ID))

        observability.flush()
        print(f"A2A task result: {task.id}")
        print(f"TRACE_ID={trace_id}")
        return trace_id
    finally:
        await client.close()
        observability.shutdown()
