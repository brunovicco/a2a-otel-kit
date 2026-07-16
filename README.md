# a2a-otel-kit

A small, typed Python 3.13 library that standardizes OpenTelemetry initialization, W3C
trace-context propagation, structured JSON logging, and privacy-safe telemetry attributes for
future A2A agents and MCP services. It is the reusable observability foundation extracted from
the `multi-agent-credit-desk` project so that it can be pip-installed independently and versioned
across multiple services.

## Scope

This library provides:

- Immutable, validated observability settings (`ObservabilitySettings`).
- Explicit tracing + structured-logging initialization and idempotent shutdown/flush
  (`Observability`).
- W3C `traceparent`/`tracestate` injection into, and extraction from, plain
  `Mapping`/`MutableMapping[str, str]` carriers - the same shape as HTTP headers, gRPC metadata,
  or message-queue headers.
- Deterministic, allowlist-based sanitization of telemetry attributes (`sanitize_attributes`).
- A versioned structured-event schema (`StructuredEvent`, `schema_version`, `event_name`,
  `event_outcome`).

This library **emits standard OTLP over HTTP and nothing else**. It does not deploy, configure,
or depend on an OTel Collector, Datadog, or Langfuse - those are operated by whatever process
consumes this library (see [Limitations](#limitations-and-deferred-work)). No vendor SDK is
imported here.

## Architecture

```text
src/a2a_otel_kit/
├── domain/         # sanitize_attributes(), StructuredEvent - pure Python, no OTel/pydantic import
├── application/     # ObservabilitySettings, TracerLifecycle port
├── adapters/        # OpenTelemetry SDK wiring (tracing.py), W3C propagation (propagation.py)
└── entrypoints/      # configure_logging(), the Observability composition root/facade
```

Dependency direction: `entrypoints -> application -> domain`, `adapters -> application/domain`.
See `docs/ARCHITECTURE.md` for the full rule set this repository enforces.

## Installation

```bash
uv add a2a-otel-kit
```

## Configuration

`ObservabilitySettings` is a frozen `pydantic-settings` model. Construct it explicitly, or load it
from `A2A_OTEL_`-prefixed environment variables (a library-specific prefix - this does not
implement the official OTel SDK auto-instrumentation environment contract):

| Field | Env var | Default | Notes |
|---|---|---|---|
| `service_name` | `A2A_OTEL_SERVICE_NAME` | required | Non-empty |
| `service_version` | `A2A_OTEL_SERVICE_VERSION` | required | Non-empty |
| `environment` | `A2A_OTEL_ENVIRONMENT` | required | Non-empty |
| `enabled` | `A2A_OTEL_ENABLED` | `False` | No-op tracing when `False` |
| `otlp_endpoint` | `A2A_OTEL_OTLP_ENDPOINT` | `None` | Required (`http://`/`https://`) when `enabled=True` |
| `otlp_timeout_seconds` | `A2A_OTEL_OTLP_TIMEOUT_SECONDS` | `10.0` | Must be positive |
| `log_level` | `A2A_OTEL_LOG_LEVEL` | `"INFO"` | Standard `logging` level name |
| `log_format` | `A2A_OTEL_LOG_FORMAT` | `"json"` | `"json"` or `"console"` |

Validation runs at construction time, before any tracer provider or exporter is built. Enabling
tracing without an endpoint raises `InvalidObservabilityConfigurationError` immediately.
`ObservabilitySettings` carries no credential or secret field, so its default `repr()` is always
safe to log.

```python
from a2a_otel_kit import Observability, ObservabilitySettings

settings = ObservabilitySettings(
    service_name="cadastral-agent",
    service_version="0.1.0",
    environment="local",
    enabled=True,
    otlp_endpoint="http://localhost:4318",  # a local OTel Collector, not a vendor endpoint
)
observability = Observability.configure(settings)
```

Leaving `enabled=False` (the default) keeps the process fully untraced: `Observability.configure()`
never requires exporter configuration in that mode.

## Lifecycle

```python
observability = Observability.configure(settings)
try:
    ...
finally:
    observability.flush()      # block until pending spans are exported
    observability.shutdown()   # release exporter resources; safe to call more than once
```

Each `Observability.configure()` call builds an independent instance with no shared global
OpenTelemetry state (no `set_tracer_provider`/`set_global_textmap` call). Repeated initialization
never raises and never corrupts a previously configured instance; when replacing an active
instance, shut the old one down first to release its resources. See `docs/adr/0002-*.md` for the
reasoning behind this choice.

## Tracing and structured events

```python
with observability.start_span("cadastral.lookup", attributes={"operation": "kyc_check"}) as span:
    observability.emit_event("cadastral.lookup.completed", "success", operation="kyc_check")
```

`start_span` produces a no-op, non-recording span when observability is disabled - callers never
need to branch on whether tracing is enabled. `emit_event` writes one structured JSON log line
carrying `schema_version`, `event_name`, and `event_outcome`, and automatically attaches
`trace_id`/`span_id` when called inside an active span. Attributes passed to either call go
through the same allowlist-and-redact sanitizer (see [Privacy guarantees](#privacy-guarantees)).

## Propagation

```python
from a2a_otel_kit import continue_trace, extract_trace_context, inject_trace_context

# Sending side (e.g. a future A2A task hand-off or MCP call):
carrier: dict[str, str] = {}
inject_trace_context(carrier)
# ... send `carrier` alongside the request, e.g. as HTTP headers ...

# Receiving side:
with continue_trace(carrier):
    with observability.start_span("financeiro.cashflow_analysis"):
        ...  # this span is a child of the sender's span
```

`inject_trace_context`/`extract_trace_context`/`continue_trace` operate on plain
`Mapping`/`MutableMapping[str, str]` carriers and never mutate OpenTelemetry's global propagator
registry, so a future HTTP, gRPC, or queue-header adapter can reuse them directly.

## Privacy guarantees

- Telemetry attributes are **deny-by-default**: `sanitize_attributes()` keeps only allowlisted
  keys (see `DEFAULT_ALLOWED_ATTRIBUTE_KEYS` in `domain/attributes.py`), rejects any key that
  looks like a credential or secret (password, token, authorization, cookie, api-key, credential,
  private-key, ssn, access-key patterns) even if the caller adds it to the allowlist, and drops
  non-scalar or oversized string values.
- There is no prompt/completion/content-capture concept anywhere in this library's public API.
  Metadata is all it ever sends - full stop, not "off by default."
- `ObservabilitySettings` has no secret-bearing field, so its representation is always safe to
  print or log; a future field named like a credential would need its own redaction and is
  guarded by a repository test (`tests/unit/test_settings.py`).
- Structured logs never carry request/response payloads, only the fields a caller explicitly
  passes through `emit_event`/`start_span`, filtered by the same allowlist.

The **boundary** this library draws: telemetry (traces, structured logs) is metadata-only by
construction here. Anything resembling artifact/content capture (prompts, documents, customer
data) belongs in an application-owned artifact store, never in telemetry - this library provides
no path to do otherwise.

## Limitations and deferred work

Deliberately out of scope for this library:

- **A2A/MCP SDK integration.** No concrete A2A or MCP SDK is depended on here. The
  carrier-based propagation helpers above are protocol-neutral so a future adapter (in a
  consuming service) can wire them into a specific transport once a pinned SDK and a verified
  integration point exist.
- **Vendor backends (Datadog, Langfuse).** This library emits OTLP and stops there. Fan-out to
  vendor backends is the responsibility of a central OTel Collector operated outside this
  library - see the sibling `multi-agent-credit-desk` repository's
  `docs/adr/0006-observability-otel-fanout-datadog-langfuse.md`. No Datadog or Langfuse SDK is a
  dependency of this package.
- **Infrastructure.** No OTel Collector config, Docker Compose stack, or deployment manifests
  live in this repository.
- **Custom OTLP authentication headers.** The exporter is constructed with an endpoint and
  timeout only; per-request auth headers for a secured OTLP endpoint are not yet supported. Add
  them at the point they become necessary, with an explicit secret-handling review at that time.

## Development

```bash
uv sync --frozen
uv run pytest
uv run python scripts/quality_gate.py
```

See `AGENTS.md` for the full engineering contract and `docs/ARCHITECTURE.md` for the enforced
dependency rules.
