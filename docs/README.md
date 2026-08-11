# Documentation

This directory contains the deeper technical documentation for `a2a-otel-kit`.

The root [README](../README.md) is intentionally optimized for discovery and adoption. Use the guides below for protocol details, architectural rationale, privacy boundaries, operations, and contribution workflows.

## Getting started

| Goal | Start here |
| --- | --- |
| Understand the project boundary | [Architecture](ARCHITECTURE.md) |
| Instrument an A2A client or server | [A2A integration](A2A.md) |
| Instrument MCP Streamable HTTP | [MCP integration](MCP.md) |
| Understand what telemetry may contain | [Privacy model](PRIVACY.md) |
| Review security boundaries and vulnerability reporting | [Security policy](../SECURITY.md) |
| Review threats, controls, and residual risks | [Threat model](THREAT_MODEL.md) |
| Measure local telemetry overhead | [Benchmarks](../benchmarks/README.md) |
| Integrate runtime evidence with governance | [Governance integration](GOVERNANCE.md) |
| Diagnose export or trace-continuity issues | [Troubleshooting](TROUBLESHOOTING.md) |

## Architecture and design

- [ARCHITECTURE.md](ARCHITECTURE.md) - layers, dependency direction, runtime flows, and verification boundaries.
- [PRIVACY.md](PRIVACY.md) - deny-by-default attribute policy and content-capture exclusions.
- [LLM_OBSERVABILITY.md](LLM_OBSERVABILITY.md) - boundary between operational telemetry and LLM/application artifacts.
- [THREAT_MODEL.md](THREAT_MODEL.md) - information-disclosure, telemetry-abuse, propagation, and availability threats.
- [adr/](adr/) - material architectural decisions and trade-offs.

## Protocol integrations

- [A2A.md](A2A.md) - official A2A SDK client/server wrapping, streaming behavior, propagation, and limitations.
- [MCP.md](MCP.md) - Streamable HTTP instrumentation through HTTPX2 and ASGI public boundaries.

## Runtime governance

- [GOVERNANCE.md](GOVERNANCE.md) - explicit delivery of sanitized structured events to `verifiable-ai-governance`.

## Operations

- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - no spans, broken parent/child relationships, duplicate wrappers, HTTP errors, shutdown, and Collector checks.

## Development

- [DEVELOPMENT.md](DEVELOPMENT.md) - local setup, quality gates, compatibility checks, packaging, and releases.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) - contributor workflow, adapter guidance, safe attributes, and PR checklist.
- [`../benchmarks/README.md`](../benchmarks/README.md) - network-free overhead methodology and explicit local OTLP mode.
- [`../SECURITY.md`](../SECURITY.md) - supported versions, private reporting, and security boundary.
- [`../CHANGELOG.md`](../CHANGELOG.md) - version history.

## Examples

The [`../examples/`](../examples/) directory contains importable adoption examples for A2A, MCP, and governance runtime telemetry.

The examples intentionally focus on instrumentation boundaries; the consuming application remains responsible for constructing its concrete SDK objects.
