# Privacy and data handling

This library is a telemetry foundation, not an application; it never handles customer or
regulated data directly. This document describes what its telemetry output can and cannot
contain by construction, for review by any project that consumes it.

## Data inventory

| Data category | Source | Purpose | Legal/contractual basis | Destination | Retention | Deletion method |
|---|---|---|---|---|---|---|
| Trace metadata (trace_id, span_id, span name, allowlisted attributes, timing) | Caller-supplied span names/attributes, OpenTelemetry SDK | Distributed tracing and correlation | Operational necessity (consuming project's basis) | OTLP/HTTP endpoint configured by the caller (typically a local OTel Collector) | Owned by the OTLP receiver, not this library | Owned by the OTLP receiver, not this library |
| Structured log fields (service, environment, version, event_name, event_outcome, allowlisted attributes, trace_id/span_id) | Caller-supplied via `emit_event`/`configure_logging` | Application-level structured logging | Operational necessity (consuming project's basis) | Process stdout | Owned by the consuming project's log pipeline | Owned by the consuming project's log pipeline |

No other data category exists in this library's scope: it does not read files, call external
APIs, or accept end-user input directly.

## OTLP authentication headers

Optional OTLP headers come from an application-owned callback invoked once by
`Observability.configure()`. Credentials are excluded from `ObservabilitySettings`, logs, spans,
events, validation details, and facade representations. Header syntax and size are validated
before exporter construction. The upstream exporter necessarily retains resolved values in
process memory until shutdown; rotation requires replacing the observability instance.

## Controls

- **Data minimization:** `sanitize_attributes()` enforces a fixed key allowlist
  (`DEFAULT_ALLOWED_ATTRIBUTE_KEYS`, `domain/attributes.py`) and rejects any value that is not a
  bounded scalar. Nothing else can reach a span or log event through this library's API.
- **Access control:** out of scope here; owned by whatever OTLP receiver and log pipeline a
  consuming project operates.
- **Encryption in transit:** delegated to the OTLP endpoint's own transport configuration
  (`https://` is supported; this library performs no additional transport hardening).
- **Encryption at rest:** out of scope; owned by the OTLP receiver/log pipeline.
- **Masking/tokenization:** sensitive-looking keys (password, token, authorization, cookie,
  api-key, credential, private-key, ssn, access-key patterns) are rejected outright rather than
  masked - see `is_sensitive_key()`/`sanitize_attributes()` in `domain/attributes.py`.
- **Non-production data strategy:** this library's own test suite uses only synthetic
  identifiers and an in-memory span exporter; no real endpoint, credential, or customer data
  appears in `tests/`.
- **Logging and tracing restrictions:** see `docs/LLM_OBSERVABILITY.md`. No vendor backend, no
  content-capture flag, and no prompt/completion field exist in this library's public API.
- **Optional A2A integration** (`adapters/a2a.py`): records only a fixed span name per operation
  and one `operation` attribute (the same fixed name, never remote-supplied data); message
  bodies, task/artifact content, agent names, URLs, header values, and exception messages are
  never recorded. See `README.md#a2a-integration`.
- **Optional MCP integration** (`adapters/mcp.py`): records only fixed Streamable HTTP operation
  names and the fixed `operation` attribute. It propagates only W3C trace context and never reads
  MCP arguments/results, HTTP bodies, arbitrary header values, URLs, or exception messages.
- **Data-subject deletion/anonymization:** not applicable; this library does not store or
  identify data subjects.
- **External processors:** none directly. A consuming project's OTel Collector and its
  downstream vendor backends are that project's processors to declare, not this library's.
- **Incident-response owner:** owned by the consuming project for its deployed telemetry
  pipeline; this library has no runtime deployment of its own.

## Prohibited logging

Secrets, authentication headers, personal identifiers, full financial identifiers, complete
request/response payloads, prompts, and model outputs containing sensitive data. This library's
API provides no field or capability through which any of these could reach a span or log event.
