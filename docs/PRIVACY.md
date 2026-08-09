# Privacy and data handling

This library is a telemetry foundation, not an application. Its built-in A2A and MCP adapters do
not inspect customer or regulated data, but the public application-span API accepts a
caller-defined span name and follows OpenTelemetry's exception-recording behavior. This document
describes the fixed adapter guarantees and the responsibilities of any project that uses the
lower-level application-span boundary.

## Data inventory

| Data category | Source | Purpose | Legal/contractual basis | Destination | Retention | Deletion method |
|---|---|---|---|---|---|---|
| Trace metadata (trace_id, span_id, span name, allowlisted attributes, timing, and optional application-span exception events) | Caller-supplied span names/attributes/exceptions, OpenTelemetry SDK | Distributed tracing and correlation | Operational necessity (consuming project's basis) | OTLP/HTTP endpoint configured by the caller (typically a local OTel Collector) | Owned by the OTLP receiver, not this library | Owned by the OTLP receiver, not this library |
| Structured log fields (service, environment, version, event_name, event_outcome, allowlisted attributes, trace_id/span_id) | Caller-supplied via `emit_event`/`configure_logging` | Application-level structured logging | Operational necessity (consuming project's basis) | Process stdout | Owned by the consuming project's log pipeline | Owned by the consuming project's log pipeline |

The library does not read application files or accept end-user input directly. When enabled, its
only outbound application-runtime network call is OTLP/HTTP trace export to the caller-configured
endpoint. Optional A2A and MCP adapters observe calls made by their wrapped SDK boundaries without
inspecting protocol content. Caller-created application spans can nevertheless expose content
through a caller-defined span name or an exception event when `record_exception=True` (the
default); sensitive boundaries must use fixed names and disable exception recording.

## OTLP authentication headers

Optional OTLP headers come from an application-owned callback invoked once by
`Observability.configure()`. Credentials are excluded from `ObservabilitySettings`, logs, spans,
events, validation details, and facade representations. Header syntax and size are validated
before exporter construction. The upstream exporter necessarily retains resolved values in
process memory until shutdown; rotation requires replacing the observability instance.

## Controls

- **Data minimization:** `sanitize_attributes()` enforces a fixed key allowlist
  (`DEFAULT_ALLOWED_ATTRIBUTE_KEYS`, `domain/attributes.py`) and rejects any attribute value that
  is not a bounded scalar. Span names and OpenTelemetry exception events are not attributes and
  cannot be sanitized by that function; callers must use fixed names and pass
  `record_exception=False` when exception content may be sensitive.
- **Access control:** out of scope here; owned by whatever OTLP receiver and log pipeline a
  consuming project operates.
- **Encryption in transit:** delegated to the OTLP endpoint's own transport configuration
  (`https://` is supported; this library performs no additional transport hardening).
- **Encryption at rest:** out of scope; owned by the OTLP receiver/log pipeline.
- **Masking/tokenization:** sensitive-looking keys (password, token, authorization, cookie,
  api-key, credential, private-key, ssn, access-key patterns) are rejected outright rather than
  masked - see `is_sensitive_key()`/`sanitize_attributes()` in `domain/attributes.py`.
- **Non-production data strategy:** all tests use synthetic identifiers and no real credential or
  customer data. Unit tests use in-memory exporters and no network. Loopback integration tests
  use ephemeral local TCP ports, and the opt-in Collector test exports only synthetic spans to a
  local Compose fixture.
- **Logging and tracing restrictions:** see `docs/LLM_OBSERVABILITY.md`. No vendor backend,
  content-capture flag, or dedicated prompt/completion field exists. The application-span API is
  intentionally generic, so caller-selected names and automatically recorded exceptions remain a
  consumer-controlled content boundary.
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
request/response payloads, prompts, and model outputs containing sensitive data. Do not place
them in attributes, event names, span names, log messages, or exceptions recorded by an
application span. The built-in A2A/MCP adapters expose none of those content fields; custom
application instrumentation remains the consumer's responsibility.
