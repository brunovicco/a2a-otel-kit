"""Minimal instrumentation helpers for official A2A clients and HTTP handlers."""

from a2a.client.client import Client
from a2a.server.request_handlers.request_handler import RequestHandler

from a2a_otel_kit.adapters.a2a import TracingClient, TracingRequestHandler
from a2a_otel_kit.entrypoints.observability import Observability


def instrument_a2a(
    client: Client, handler: RequestHandler, observability: Observability
) -> tuple[Client, RequestHandler]:
    """Wrap both public A2A HTTP boundaries without changing their SDK contracts."""
    return (
        TracingClient.wrap(client, observability),
        TracingRequestHandler.wrap(handler, observability),
    )
