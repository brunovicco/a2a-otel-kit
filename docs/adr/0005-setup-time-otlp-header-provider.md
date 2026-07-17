# ADR-0005: Resolve OTLP headers through a setup-time provider

## Status

Accepted

## Date

2026-07-17

## Context

Some OTLP/HTTP endpoints require authentication headers. Adding those values to
`ObservabilitySettings` would retain credential material in a Pydantic model whose representation
is intentionally safe to log. Reading a specific secret manager in the library would also couple
the vendor-neutral composition root to infrastructure selected by an application.

## Decision

`Observability.configure` accepts an optional application-owned `OTLPHeadersProvider` callable.
When tracing is enabled, the provider is invoked exactly once during setup and its returned string
mapping is validated before it is passed to the OTLP HTTP exporter. Header names reject empty,
non-token, colon, CR, and LF characters; values reject CR and LF. Count and size limits bound
memory use and prevent an untrusted provider from constructing arbitrarily large requests.
Validation and provider-failure messages
never include header names, values, or the original exception text. Disabled tracing does not
invoke the provider. Neither the provider nor its result is stored in `ObservabilitySettings`.

## Alternatives considered

- Secret-bearing settings or environment fields were rejected because model representations and
  configuration diagnostics would acquire a secret-redaction obligation.
- A plain headers mapping was rejected because a provider permits just-in-time retrieval from a
  caller-owned secret manager and avoids constructing credentials before setup.
- Vendor-specific authentication clients were rejected because this library emits vendor-neutral
  OTLP and must not own backend credentials or refresh protocols.

## Consequences

Applications can authenticate direct OTLP export without placing credentials in the library's
safe configuration model. Credentials are resolved once, not refreshed automatically. The OTel
exporter necessarily retains the resulting headers for later requests until shutdown.

## Security and privacy impact

Secret values are passed only to the upstream exporter. They are never logged, interpolated into
errors, added to telemetry, or exposed from the public `Observability` facade. Providers remain
responsible for securing their source and returning only the minimum required headers.

## Operational impact

Credential rotation requires configuring a new `Observability` instance and shutting down the old
one. Provider failures fail setup before application traffic begins. Deployments that export to a
local unauthenticated Collector need no provider and behave as before.

## Follow-up

- Revisit refreshable credentials only when an actual backend requires rotation without process
  or observability-instance replacement.
- Keep header validation aligned with the OTLP HTTP exporter and HTTP syntax.
