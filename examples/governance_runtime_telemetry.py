"""Minimal explicit adoption of the Governance runtime telemetry sink."""

import asyncio
import os

from a2a_otel_kit.adapters.governance import (
    GovernanceRuntimeTelemetrySettings,
    GovernanceRuntimeTelemetrySink,
)
from a2a_otel_kit.domain.attributes import StructuredEvent, StructuredEventOutcome


async def main() -> None:
    """Deliver one already-structured, content-free operational event."""
    settings = GovernanceRuntimeTelemetrySettings(
        base_url=os.environ["GOVERNANCE_BASE_URL"],
        agent_id=os.environ["GOVERNANCE_AGENT_ID"],
        service="example-agent",
        environment=os.getenv("APP_ENV", "local"),
        version="0.1.0",
    )
    sink = GovernanceRuntimeTelemetrySink(
        settings,
        credential_provider=lambda: os.environ["GOVERNANCE_RUNTIME_TELEMETRY_API_KEY"],
    )
    event = StructuredEvent(
        event_name="example.operation.completed",
        event_outcome=StructuredEventOutcome.SUCCESS,
        attributes={"operation": "example.operation"},
    )
    await sink.emit(event)


if __name__ == "__main__":
    asyncio.run(main())
