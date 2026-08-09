"""Shared configuration for the end-to-end demo."""

from a2a_otel_kit import Observability, ObservabilitySettings

OTLP_ENDPOINT = "http://127.0.0.1:4318/v1/traces"
MCP_URL = "http://127.0.0.1:8102/mcp"
RISK_AGENT_URL = "http://127.0.0.1:8101"
PRIVATE_CUSTOMER_ID = "customer-private-123"


def configure_observability(service_name: str) -> Observability:
    """Configure metadata-only OpenTelemetry export for one demo service."""
    return Observability.configure(
        ObservabilitySettings(
            service_name=service_name,
            service_version="demo",
            environment="local-demo",
            enabled=True,
            otlp_endpoint=OTLP_ENDPOINT,
        )
    )
