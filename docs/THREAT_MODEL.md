# Threat model

## Scope and assets

This model covers `a2a-otel-kit` telemetry creation, W3C context propagation, the fixed A2A and MCP
Streamable HTTP adapters, OTLP/HTTP export, and structured events. It does not model the consuming
application's business logic, identity system, Collector deployment, or telemetry backend except
where their behavior crosses the library boundary.

Assets to protect are prompts and model responses, A2A/MCP and business payloads, credentials,
personal data, trustworthy service operation, and the usefulness of telemetry for diagnosis.

## Trust boundaries and assumptions

```text
untrusted remote peer
        │ trace context + protocol traffic
        ▼
consumer transport / a2a-otel-kit adapter
        │ sanitized metadata + spans
        ▼
OpenTelemetry SDK ── OTLP/HTTP ── Collector ── telemetry backend
        ▲
        │ caller-defined span names, exceptions, and allowlisted attributes
consumer application
```

- Protocol requests, remote trace context, caller-supplied attributes, exception objects, OTLP
  header providers, and Collector responses are untrusted at their respective boundaries.
- The consuming service authenticates and authorizes protocol requests independently of tracing.
- The deployment protects exporter credentials, TLS configuration, Collector access, storage,
  retention, and deletion.
- W3C trace context provides correlation only. It is not proof of identity, integrity, tenant, or
  authorization.

## Threats and controls

### Information disclosure

#### Prompt leakage

The fixed A2A/MCP adapters do not read prompts, messages, model responses, MCP arguments/results,
or bodies, and their telemetry schema has no content-bearing field. `sanitize_attributes()` drops
unknown keys and nested or oversized values.

Residual risk: application code can put prompt fragments in a caller-controlled span name, an
allowlisted string attribute, a structured-log event outside this library, or an exception.
`Observability.start_span()` records exceptions by default. Sensitive application spans must use
fixed names, pass `record_exception=False`, and set a safe error status without exception text.

#### Business payload leakage

Protocol adapters observe lifecycle and fixed operation metadata rather than payload content. The
end-to-end demo asserts that a planted private business identifier is absent from exported trace
telemetry.

Residual risk: the demo is evidence for its covered flow, not a proof about consumer code,
custom adapters, vendor processors, or all future SDK behavior. Consumers must review custom
instrumentation and Collector processors and must not map identifiers or payload fields into
telemetry.

#### Credential leakage

Credential-shaped attribute keys are rejected even when explicitly allowlisted.
`ObservabilitySettings` cannot represent credentials. OTLP headers come from a caller-owned
provider and validation errors omit both provider output and underlying exception text.

Residual risk: a consumer can still embed a secret in a span name, exception message, endpoint
URL, unrelated log, or deployment configuration. Use secret management, HTTPS for remote export,
least-privilege exporter credentials, and backend access controls.

### Telemetry abuse

#### Cardinality explosion

Built-in adapter span names and `operation` attributes are fixed and low-cardinality. Attribute
strings are bounded, and unknown keys are dropped.

Residual risk: application span names and values of otherwise allowed keys remain caller
controlled. Apply fixed vocabularies at application boundaries, sampling and rate limits at the
SDK/Collector, and backend quotas. A bounded string length is not a cardinality bound.

#### Forged attributes

Sanitization constrains keys and value types but does not establish that an allowed value is true.
Remote data must not be copied into attributes without application validation.

Residual risk: a compromised process or faulty consumer can emit plausible but false telemetry.
Do not use ordinary traces as an immutable audit record. Governance evidence requires its own
authenticated ingestion, authorization, integrity, and reconciliation controls.

#### Telemetry poisoning

Fixed protocol vocabulary and scalar/size limits reduce arbitrary data injection. Telemetry
destinations remain deployment-controlled rather than hidden inside library calls.

Residual risk: valid but attacker-selected request volume, trace identifiers, timing, and outcomes
can skew dashboards and alerts. Collectors and backends should enforce tenant isolation, quotas,
sampling, anomaly detection, and restricted write access.

### Trace propagation

#### Malformed `traceparent`

Parsing is delegated to OpenTelemetry's W3C propagator; malformed context does not become a valid
remote parent. Transport and application validation remain independent.

Residual risk: parser defects or divergent upstream SDK behavior are dependency risks. Keep the
OpenTelemetry range current and test supported versions. Never treat a parse failure as an
authorization signal.

#### Untrusted remote context

A syntactically valid remote context is accepted for continuation so distributed correlation can
work. That context may have been created by an attacker and can influence the trace identifier and
sampling bit.

Residual risk: cross-tenant linkage, confusing topology, and sampling manipulation are possible at
public boundaries. A deployment that cannot trust upstream context should discard it or start a
new trace according to its tenant and sampling policy.

#### Context spoofing

Trace and span identifiers are not identities and have no authenticity guarantee. The library does
not use them for access control.

Residual risk: dashboards or operators may over-trust a coherent-looking trace. Correlate security
events with authenticated principal and audit data kept outside trace context; never infer actor,
tenant, or authorization from a trace ID.

### Availability

#### Exporter failure

The SDK exporter uses an explicit configured timeout and batch processing. Normal span completion
does not wait for each OTLP request; callers explicitly flush and shut down at lifecycle
boundaries.

Residual risk: queues can fill, spans can be dropped, exporter threads consume resources, and an
explicit flush can block up to its timeout. Monitor export failures and dropped telemetry, bound
timeouts, and treat telemetry loss separately from business failure.

#### Collector unavailable

The library does not retry business operations because telemetry export fails, and it does not
own Collector recovery. The local integration and end-to-end fixtures verify receipt and cleanup,
not production high availability.

Residual risk: upstream exporter retry/queue behavior and repeated connection failure can consume
CPU, memory, sockets, and shutdown time. Deploy redundant or local Collectors, set capacity and
backpressure limits, and alert on export health.

#### Observability affecting the business path

Tracing is explicit, importing the package performs no I/O, disabled tracing is a no-op, and fixed
adapters avoid payload inspection. Network export is performed by the batch processor rather than
inline with every operation.

Residual risk: local span creation, propagation, sanitization, logging, SDK defects, configuration
errors, and resource exhaustion can still add latency or raise errors. Benchmark the actual
deployment, fail startup on invalid required configuration, keep telemetry calls outside critical
irreversible mutations where possible, and preserve application-level timeout and idempotency
controls. This library does not guarantee zero overhead or complete failure isolation.

## Consumer review checklist

- Are application span names fixed and free of tenant, prompt, payload, and credential data?
- Do sensitive application spans disable exception recording and set safe status values?
- Are authentication and authorization independent of trace context?
- Is remote context discarded or restarted at boundaries where upstream trust is insufficient?
- Are Collector credentials, TLS, access, retention, deletion, and tenant isolation configured?
- Are cardinality, sampling, queue, retry, timeout, and backend quota limits monitored?
- Have custom adapters and logging processors been reviewed for content capture?
- Are telemetry gaps treated as observability failures rather than successful business evidence?

## Known coverage gaps

A2A JSON-RPC/REST and MCP Streamable HTTP are covered. A2A gRPC context continuity is not verified;
MCP stdio and legacy SSE are not instrumented. See the protocol guides and
[security policy](../SECURITY.md) before extending those boundaries.
