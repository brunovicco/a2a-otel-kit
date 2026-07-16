# LLM and vendor observability policy

This library provides a vendor-neutral OpenTelemetry foundation only: tracing, W3C trace-context
propagation, structured JSON logging, and privacy-safe attribute sanitization, all emitting
standard OTLP over HTTP. **It does not contain, and will not add, a Langfuse, Datadog, or any
other vendor-specific SDK.** That constraint is deliberate, not an oversight - see
`AGENTS.md` and `.claude/rules/security-privacy.md`.

## Why not a Langfuse/Datadog adapter here

An earlier planning document for the sibling `multi-agent-credit-desk` project described a
Langfuse-specific tracing adapter as planned for this repository. That plan predates
`multi-agent-credit-desk`'s `docs/adr/0006-observability-otel-fanout-datadog-langfuse.md`, which
places vendor fan-out at a central OTel Collector instead: this library emits OTLP, and a
Collector operated by the consuming project's infrastructure fans that OTLP out to whichever
vendor backends (Datadog, Langfuse, or others) that project chooses to run. Embedding a vendor SDK
directly in a reusable library would:

- couple every consumer of this library to one vendor's SDK and account, even projects that never
  want that vendor;
- duplicate what the Collector already does, with a second, harder-to-audit fan-out path;
- make "vendor-neutral by design" false advertising.

## What this library does instead

- `Observability.configure(settings)` builds a real tracer only when
  `settings.enabled=True` and `settings.otlp_endpoint` is set; otherwise every span is a no-op.
- Spans and structured log events carry only allowlisted, scalar attributes
  (`sanitize_attributes()` in `domain/attributes.py`) - no prompts, completions, documents, or
  customer data ever flow through this library's telemetry path, with or without a vendor
  backend attached. There is no "content capture" flag anywhere in this library because there is
  no content-capable field to gate.
- `docs/PRIVACY.md` documents the data this library's telemetry does and does not carry.

## Where LLM-call-level tracing (cost, tokens, prompts) belongs

If a consuming service later wants prompt/completion-level tracing (e.g. via a Langfuse SDK
integration for cost/token/eval data), that adapter belongs in the consuming service or in a
separate, explicitly vendor-coupled package - never in this library. Any such adapter must still
follow the metadata-by-default principle: no prompt/completion content without an explicit,
documented, approved opt-in, exactly as `multi-agent-credit-desk`'s
`docs/adr/0007-telemetry-without-sensitive-content.md` requires.
