# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

PyPI publication status for each version is recorded in this file, not restated elsewhere.
`v0.3.0` is tagged in git but was cut before this project's release tooling existed: its tree has
no `LICENSE`, no PEP 639 license metadata, and not even `.github/workflows/release.yml` itself, so
publishing it would ship a non-compliant package. **`v0.3.0` must never be published to PyPI.**
`v0.3.1` is the first version intended for publication. `0.1.0` and `0.2.0` are reconstructed from
the `pyproject.toml` version present at their respective commits and were never tagged or released
independently.

## [0.3.1] - 2026-07-16

Release-readiness commit: adds packaging and release infrastructure only. Library behavior is
unchanged from 0.3.0 - no domain, application, adapter, or entrypoint code changed.

### Added

- An MIT `LICENSE` and PEP 639 SPDX license metadata (`license`, `license-files`) in
  `pyproject.toml`, plus expanded classifiers, keywords, and `[project.urls]`.
- An exact build-backend pin, `hatchling==1.31.0` (verified against live PyPI; see
  `docs/DEVELOPMENT.md#build-backend` for why an exact pin is used instead of a range, and how to
  upgrade it deliberately).
- An explicit sdist file list (`[tool.hatch.build.targets.sdist]`).
- `scripts/verify_release_artifacts.py`: inspects a built wheel/sdist for required modules,
  `py.typed`, and metadata (name, version, license expression, `a2a`/`mcp` extras), then smoke-tests
  base/`a2a`/`mcp` installs in isolated, network-blocked virtual environments.
- `scripts/validate_release_ref.py`: validates a release ref/version against `pyproject.toml`,
  peels the requested tag to its commit SHA, and proves the checked-out tree matches that SHA
  before any privileged workflow step runs. Every job downstream of validation re-derives this
  proof independently rather than trusting the tag name a second time.
- `.github/workflows/release.yml`: a least-privilege, `workflow_dispatch`-only GitHub Actions
  workflow. Validation binds the release to one immutable commit SHA via job outputs; every later
  job checks out that SHA (never the raw tag input) and re-verifies the tag has not moved before
  doing anything privileged. Builds once, verifies the built artifacts, publishes to PyPI via
  Trusted Publishing (no stored token), and only then creates a GitHub Release - using the
  validated short tag name, not `refs/tags/...` - with the wheel, sdist, `SHA256SUMS`, and a
  build-provenance attestation attached.
- `.github/workflows/quality.yml`: an additional read-only `build-and-verify` job.

## [0.3.0] - 2026-07-16

**Not published to PyPI, and must never be - see the note at the top of this file.**

### Added

- Optional MCP Streamable HTTP integration (`mcp` extra, `adapters/mcp.py`):
  `TracingAsyncTransport` for outbound HTTPX-based MCP clients and `TracingASGIMiddleware` for
  inbound `FastMCP` Streamable HTTP servers. Both `wrap()` entry points are idempotent. Only fixed,
  low-cardinality operation names and one `operation` attribute are recorded. Outbound spans use
  `SpanKind.CLIENT`; inbound spans use `SpanKind.SERVER`. See
  `docs/adr/0004-mcp-streamable-http-boundaries.md`.

### Security

- The MCP adapter propagates only W3C `traceparent`/`tracestate` and never reads MCP arguments,
  results, request/response bodies, arbitrary header values, URLs, or exception text. HTTP 4xx/5xx
  responses produce an ERROR span and one `failed` event without reading the response body.

### Known limitations

- Only the Streamable HTTP transport is covered; stdio and legacy SSE transports are explicitly
  out of scope.

## [0.2.0] - 2026-07-16

### Added

- Optional A2A SDK integration (`a2a` extra, `adapters/a2a.py`): `TracingClient` (outbound,
  `SpanKind.CLIENT`) and `TracingRequestHandler` (inbound JSON-RPC/REST, `SpanKind.SERVER`), both
  idempotent to wrap. Deterministic streaming cleanup for `send_message`, `subscribe`,
  `on_message_send_stream`, and `on_subscribe_to_task`, with exactly one terminal
  `completed`/`failed` structured event emitted per operation regardless of how the stream ends
  (exhaustion, exception, explicit `aclose()`, or cancellation). See
  `docs/adr/0003-a2a-request-response-wrapping.md`.

### Security

- Message bodies, task/artifact content, agent names, URLs, header values, and exception messages
  are never recorded in a span or structured event; a failure is signaled by span status and event
  outcome alone.

### Known limitations

- Inbound trace-context continuity is unverified for the gRPC transport, which builds its server
  call context from gRPC servicer context rather than Starlette request headers.

## [0.1.0] - 2026-07-16

### Added

- `ObservabilitySettings`: an immutable, validated `pydantic-settings` configuration model backed
  by `A2A_OTEL_`-prefixed environment variables, with `enabled=False` as a fully no-op default that
  requires no exporter configuration.
- `Observability`: explicit, per-instance tracing and structured-logging initialization with
  idempotent `flush()`/`shutdown()`. Each instance owns independent OpenTelemetry state; no global
  `set_tracer_provider`/`set_global_textmap` call is made.
- W3C `traceparent`/`tracestate` propagation (`inject_trace_context`, `extract_trace_context`,
  `continue_trace`) over plain `Mapping`/`MutableMapping[str, str]` carriers, independent of any
  specific transport.
- Deterministic, allowlist-based `sanitize_attributes()` and a versioned structured-event schema
  (`StructuredEvent`, `schema_version`, `event_name`, `event_outcome`).
- Structured JSON logging via `configure_logging()`, with `trace_id`/`span_id` automatically
  attached to events emitted inside an active span.

### Security

- Telemetry attributes are deny-by-default: `sanitize_attributes()` keeps only allowlisted keys,
  rejects any key resembling a credential or secret even if explicitly allowlisted, and drops
  non-scalar or oversized string values.
- `ObservabilitySettings` carries no secret-bearing field, so its default representation is always
  safe to log.
