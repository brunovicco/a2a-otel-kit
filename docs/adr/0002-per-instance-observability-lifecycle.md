# ADR-0002: Per-instance observability lifecycle, no global OpenTelemetry state

- Status: Accepted
- Date: 2026-07-16

## Context

`Observability.configure(settings)` must be explicit (never run automatically at import) and
idempotent (safe to call more than once), and `shutdown()` must be safe to call more than once.
OpenTelemetry's own API offers a global registration path
(`opentelemetry.trace.set_tracer_provider`, `opentelemetry.propagate.set_global_textmap`) that
most auto-instrumentation libraries rely on. Using it here would make repeated `configure()` calls
either raise (the SDK logs a warning and refuses to override an already-set global provider) or
silently produce confusing double-registration, and would make this library's behavior depend on
whatever else in a process has touched OpenTelemetry's global state - a poor fit for a library
that other services embed and that must be testable in isolation.

## Decision

`Observability.configure()` never calls `set_tracer_provider` or `set_global_textmap`. Each call
builds and returns a fully independent `Observability` instance, holding its own `TracerProvider`
(or `NoOpTracerProvider` when disabled) and its own tracer. Propagation
(`inject_trace_context`/`extract_trace_context`/`continue_trace` in `adapters/propagation.py`)
uses a single, stateless, module-level `TraceContextTextMapPropagator` instance directly, rather
than OpenTelemetry's global propagator registry - trace-context inject/extract works off the
ambient `opentelemetry.context` contextvars state, which is process-wide by OpenTelemetry's own
design regardless of which `TracerProvider` created a given span, so no provider-level global
registration is needed for propagation to work correctly.

`shutdown()` is guarded by an internal `_is_shut_down` flag and no-ops on a second call and when
there is nothing to shut down (the disabled/no-op case, where the lifecycle handle is `None`).

## Consequences

- Calling `configure()` twice never raises and never corrupts a previously configured instance's
  state - each instance is independent. This makes tests trivially isolated: no test needs to
  reset OpenTelemetry's global provider registry between cases.
- The trade-off: replacing an active `Observability` instance with a new one does not
  automatically release the old instance's exporter/background-thread resources. Callers that
  reconfigure at runtime must call `shutdown()` on the instance being replaced. This is
  documented in `README.md`'s Lifecycle section; it is not expected to matter for the normal case
  of configuring once at process startup and shutting down once at process exit.
- Because propagation never touches global OpenTelemetry state, a consuming service can safely
  run multiple independent `Observability` instances (for example, in a test harness or a
  multi-tenant worker) without one instance's configuration leaking into another's spans.
