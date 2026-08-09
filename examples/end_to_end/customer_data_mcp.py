"""Customer-data MCP service used by the end-to-end demo."""

from typing import cast

import uvicorn
from common import configure_observability
from mcp.server import MCPServer

from a2a_otel_kit.adapters.mcp import ASGIApp, TracingASGIMiddleware

observability = configure_observability("customer-data-mcp")
mcp_server = MCPServer("customer-data-demo")


@mcp_server.tool()
def get_customer_risk_score(customer_id: str) -> int:
    """Return the deterministic synthetic risk score used by the demo."""
    del customer_id
    return 32


app = TracingASGIMiddleware.wrap(
    cast(
        ASGIApp,
        mcp_server.streamable_http_app(stateless_http=True, json_response=True),
    ),
    observability,
)

if __name__ == "__main__":
    try:
        uvicorn.run(app, host="127.0.0.1", port=8102, log_level="warning")
    finally:
        observability.flush()
        observability.shutdown()
