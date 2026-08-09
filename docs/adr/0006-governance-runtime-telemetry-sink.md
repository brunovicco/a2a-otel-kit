# ADR-0006: Explicit Governance runtime telemetry sink

## Status

Accepted.

## Context

`a2a-otel-kit` already owns the privacy boundary for structured telemetry: attributes are
deny-by-default, sensitive-looking keys are removed, arbitrary content is not part of the public
telemetry API, and structured events use a closed outcome vocabulary.

`verifiable-ai-governance` P1.7a introduced a separate durable ingestion boundary for sanitized
runtime evidence. That boundary accepts a closed JSON contract over HTTP and authenticates each
producer with a credential bound to a governed Agent.

Automatically performing HTTP delivery from `Observability.emit_event()` would make an existing
synchronous logging API perform hidden network I/O, could block an async event loop, and would
couple the vendor-neutral observability facade to a specific governance product.

## Decision

Provide an explicit adapter in `a2a_otel_kit.adapters.governance`.

The adapter:

- accepts `StructuredEvent` rather than arbitrary dictionaries;
- re-runs `sanitize_attributes()` before constructing the outbound contract;
- adds service/environment/version from non-secret adapter settings;
- copies only valid active OpenTelemetry `trace_id` and `span_id`;
- maps only fields explicitly accepted by the Governance P1.7a contract;
- generates a UUID event identifier once before delivery;
- reuses exactly the same serialized body and event identifier for internal retries;
- retries only bounded transient transport/status failures;
- does not read or persist Governance response bodies;
- resolves the machine credential outside representable settings;
- never includes credential values or remote error bodies in raised messages;
- permits cleartext HTTP only for loopback/local development.

The adapter is not imported by the package root and is never activated automatically.

## Consequences

Applications opt in explicitly and decide whether a delivery failure is fail-open or fail-closed
for their own business workflow.

The kit remains usable without Governance and without an additional HTTP dependency: the adapter
uses the Python standard library transport behind `asyncio.to_thread()` so it does not block the
caller event loop.

P1.7c may adopt this adapter in `multi-agent-credit-desk` without changing the generic
`Observability` API. P1.7d will provide live cross-repository evidence against the real Governance
ingestion endpoint.
