# Security policy

## Supported versions

Security fixes are applied to the current minor release line and to `main`. Older minor releases
should be upgraded before a fix is requested.

| Version | Supported |
| --- | :---: |
| `0.5.x` | Yes |
| `< 0.5` | No |

## Reporting vulnerabilities

Report suspected vulnerabilities privately through
[GitHub Security Advisories](https://github.com/brunovicco/a2a-otel-kit/security/advisories/new).
Include the affected version, a minimal reproduction, impact, and any known mitigations. Do not
include credentials, prompts, business payloads, or personal data in the report, and do not open a
public issue before a coordinated fix is available.

Maintainers will acknowledge the report, assess severity and affected versions, and coordinate a
fix and disclosure with the reporter. This project does not promise a fixed response SLA.

## Security boundary

`a2a-otel-kit` instruments explicit A2A and MCP Streamable HTTP boundaries and exports
vendor-neutral telemetry. It does not provide authentication, authorization, transport security,
an OpenTelemetry Collector, backend access control, retention enforcement, or an incident-response
system. Those controls belong to the consuming service and its deployment platform.

The built-in A2A and MCP adapters create fixed, low-cardinality span names and attributes. They
start their spans with `record_exception=False`, set safe status values, and do not inspect or
record request bodies, response bodies, prompts, MCP arguments/results, arbitrary headers, URLs,
or exception messages.

Caller-created application spans have a different boundary. `Observability.start_span()` accepts a
caller-controlled name and allowlisted attributes, and `record_exception=True` by default. An
exception escaping that context can therefore add its type, message, and stack trace to telemetry.
Applications handling sensitive exceptions must pass `record_exception=False`, set a safe status
themselves, and avoid content-bearing span names. This library cannot sanitize arbitrary exception
objects or span names after the caller gives them to OpenTelemetry.

See [the threat model](docs/THREAT_MODEL.md) for trust boundaries, mitigations, and residual risks.

## Telemetry data policy

Library-owned protocol telemetry is metadata-only. Attributes pass through a deny-by-default
allowlist; sensitive-looking keys, nested values, unsupported values, and oversized strings are
dropped. Fixed adapters do not expose a content-capture switch because their telemetry contracts
contain no prompt or business-payload field.

Consumers remain responsible for:

- choosing privacy-safe application span names and attribute values;
- configuring Collector/backend access, processors, retention, deletion, and regional routing;
- reviewing any custom instrumentation or vendor integration outside this library; and
- preventing personal or confidential data from entering exception messages recorded by
  caller-created application spans.

The detailed data inventory and handling expectations are in [the privacy model](docs/PRIVACY.md)
and [the LLM observability boundary](docs/LLM_OBSERVABILITY.md).

## Credential handling

`ObservabilitySettings` has no credential fields. Authenticated OTLP export uses a caller-owned
`OTLPHeadersProvider`, resolved once during explicit configuration. Header names, values, count,
and total size are validated without rendering provider output or underlying exception text in
errors. Credentials must come from a deployment secret mechanism, use least privilege, and never
be committed, logged, embedded in URLs, or placed in trace attributes.

Use TLS (`https://`) for non-loopback OTLP endpoints and configure certificate verification at the
deployment boundary. Rotate or revoke exporter credentials through the consuming platform; this
library does not provide per-request credential rotation.

## Trace-context trust assumptions

W3C `traceparent` and `tracestate` are correlation metadata, not authentication or authorization.
Remote callers can forge valid context, choose trace identifiers, and influence sampling flags.
Never grant access, select a tenant, make a billing decision, or establish audit identity from
trace context.

Validate identity and permissions independently at every protocol boundary. At public trust
boundaries, deployments should discard or restart untrusted trace context when cross-tenant trace
linkage is unacceptable. Malformed context is handled by the OpenTelemetry propagator, but valid
context remains untrusted.

## Dependency policy

Runtime dependencies are bounded in `pyproject.toml`, resolved in `uv.lock`, and checked by CI.
Changes must justify each new dependency and review its maintenance, provenance, known
vulnerabilities, and license. The quality gate runs dependency and static security checks; CI also
tests the minimum and newest bounded A2A/MCP SDK combinations. A clean scanner result reduces risk
but does not replace review or timely upgrades.
