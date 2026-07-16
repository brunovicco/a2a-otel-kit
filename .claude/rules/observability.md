---
paths:
  - "src/**/*.py"
---

# Logging and observability rules

- Emit structured logs with stable event names.
- Prefer keyword fields over interpolated prose.
- Include service, environment, version, outcome, duration, correlation ID, and trace ID when applicable.
- Use UTC timestamps.
- Log exceptions once at the boundary that handles them.
- Redact by allowlist; never dump arbitrary objects or payloads.
- Separate logs, metrics, traces, and immutable audit events by purpose.
- Add metrics for latency, throughput, errors, retries, circuit state, queue lag, and business outcomes where relevant.
- Propagate W3C trace context across HTTP and messaging boundaries.
- `print()` is prohibited in production code.
- Call `configure_logging()` from `entrypoints/logging.py` once at process startup; never configure logging elsewhere.
- This library emits vendor-neutral OTLP only; never add a Datadog, Langfuse, or other vendor SDK dependency here. See `docs/LLM_OBSERVABILITY.md` for why vendor fan-out stays outside this library.
- Telemetry attributes must go through `sanitize_attributes()` (`domain/attributes.py`); never pass an arbitrary dict directly to a span or log call.
