# Governance runtime telemetry

`a2a-otel-kit` includes an optional, explicit adapter for sending sanitized runtime telemetry to `verifiable-ai-governance`.

The integration is deliberately outside the generic `Observability.emit_event()` path.

## Why explicit delivery?

Local observability and remote governance evidence have different failure and ownership semantics.

A call such as:

```python
observability.emit_event(...)
```

must not unexpectedly perform remote governance I/O.

The consuming application therefore decides:

- which structured events become governance evidence;
- whether governance delivery failures affect the business path;
- which credentials are used;
- where the governance endpoint is located;
- when retries are appropriate.

## Basic usage

```python
import os

from a2a_otel_kit.adapters.governance import (
    GovernanceRuntimeTelemetrySettings,
    GovernanceRuntimeTelemetrySink,
)
from a2a_otel_kit.domain.attributes import (
    StructuredEvent,
    StructuredEventOutcome,
)

settings = GovernanceRuntimeTelemetrySettings(
    base_url="https://governance.example.com",
    agent_id="11111111-1111-4111-8111-111111111111",
    service="decision-agent",
    environment="production",
    version="1.0.0",
)

sink = GovernanceRuntimeTelemetrySink(
    settings,
    credential_provider=lambda: os.environ[
        "GOVERNANCE_RUNTIME_TELEMETRY_API_KEY"
    ],
)

await sink.emit(
    StructuredEvent(
        event_name="decision.completed",
        event_outcome=StructuredEventOutcome.SUCCESS,
        attributes={"operation": "decision"},
    )
)
```

## Data flow

```text
Application
    │
    ├── local StructuredEvent
    │          │
    │          ├──▶ structured log / trace correlation
    │          │
    │          └──▶ explicit GovernanceRuntimeTelemetrySink
    │                         │
    │                         ├── re-sanitize attributes
    │                         ├── attach valid active trace/span IDs
    │                         ├── build closed governance contract
    │                         └── deliver with stable event identity
    │
    ▼
business path remains application-controlled
```

## Security properties

The adapter applies the library privacy boundary again before delivery.

It:

- re-sanitizes event attributes;
- ignores unknown or content-bearing keys;
- includes trace/span identifiers only when valid and active;
- keeps credentials outside the safe-to-represent settings object;
- does not retain credential material in settings;
- requires HTTPS for remote endpoints;
- allows cleartext HTTP only for loopback development.

## Retry and idempotency

Internal retries reuse the same event identifier and serialized body.

That property lets the receiving governance service apply idempotency without treating retry attempts as independent runtime events.

The adapter does not recursively rewrite events or mutate business payloads.

## Failure semantics

The application owns the decision about whether governance delivery failure is:

- best-effort telemetry;
- retryable infrastructure failure;
- a degraded-state signal;
- or a fail-closed condition for a specific regulated workflow.

Do not hide that decision inside a generic logging facade.

## Relationship with OpenTelemetry

Governance telemetry complements OpenTelemetry; it does not replace it.

```text
                         ┌──▶ OTLP / tracing backend
Agent ─▶ a2a-otel-kit ───┤
                         └──▶ governance runtime evidence
```

OpenTelemetry answers operational questions such as latency, topology, and failures.

Governance evidence can answer policy and audit questions about explicitly selected runtime events.

A shared trace ID can correlate both paths without sending prompts or business payloads into telemetry.

## Related documentation

- [Privacy](PRIVACY.md)
- [Architecture](ARCHITECTURE.md)
- [LLM observability](LLM_OBSERVABILITY.md)
- [Troubleshooting](TROUBLESHOOTING.md)
