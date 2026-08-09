# Contributing

Thank you for improving `a2a-otel-kit`. Keep changes focused, written in English, and aligned with
the repository engineering contract in [AGENTS.md](AGENTS.md).

## Setup

Install Python 3.13 or 3.14 and [uv](https://docs.astral.sh/uv/), then create the locked development
environment:

```bash
uv python install
uv sync --frozen --all-groups
```

## Quality gate

Run focused checks while iterating and the complete gate before requesting review:

```bash
uv run ruff check <changed paths>
uv run mypy <changed Python paths>
uv run pytest <relevant tests>
uv run python scripts/quality_gate.py
```

Do not weaken lint, typing, coverage, architecture, or security configuration to make a change
pass. See [the development guide](docs/DEVELOPMENT.md) for integration, build, and release checks.

## Architecture rules

Preserve the enforced dependency direction:

```text
entrypoints -> application -> domain
adapters    -> application / domain
domain      -> no outer layer
```

Domain code stays framework-independent. Application code owns use cases and consumer-defined
ports. Adapters translate infrastructure behavior at the boundary, and entrypoints validate
external input and compose the application. Add abstractions only for a demonstrated variation.

## Adding an adapter

- Put optional SDK integration in `src/a2a_otel_kit/adapters/`; do not leak SDK types into inner
  layers.
- Instrument public, stable boundaries and make wrapping idempotent.
- Validate external data and translate infrastructure exceptions without exposing content.
- Add explicit timeouts. Retry only transient, repeatable work with bounded backoff and jitter.
- Preserve business idempotency and never let telemetry retries repeat a business operation.
- Add the optional dependency deliberately, review its license/security/maintenance, and update
  compatibility policy and documentation.
- Add unit tests plus realistic contract or integration coverage for the boundary.

## Adding telemetry attributes safely

All attributes must pass through `sanitize_attributes()`. Extend the allowlist narrowly in the
domain only when the key has a documented operational purpose, bounded cardinality, scalar value,
and no prompt, payload, personal-data, credential, or free-form exception content. Sensitive-looking
keys remain forbidden even if requested by a caller.

Built-in adapters use fixed span names and fixed operation values. Caller-created application
spans record exceptions by default; pass `record_exception=False` at sensitive boundaries and set
a content-free status explicitly. Read [SECURITY.md](SECURITY.md),
[the threat model](docs/THREAT_MODEL.md), and [the privacy model](docs/PRIVACY.md).

## Tests required

Add behavior tests for new work and a regression test for each fix. Unit tests must not use real
network, databases, queues, clocks, randomness, or external filesystems. Use integration/contract
tests at real SDK or transport boundaries and reserve end-to-end tests for critical flows. Where
side effects matter, cover duplicate, retry, timeout, cancellation, concurrency, and partial
failure behavior.

## ADR expectations

Add an Architecture Decision Record under `docs/adr/` when a change materially alters dependency
direction, lifecycle ownership, a public boundary, security/privacy policy, or a lasting trade-off.
Small implementation details and documentation-only clarifications do not need an ADR. Follow the
existing numbered ADR format and link the decision from relevant documentation.

## Pull-request checklist

- [ ] The change is focused and contains no unrelated edits.
- [ ] Public behavior, compatibility, security, privacy, and operational impacts are documented.
- [ ] New or changed Python is fully typed and has Google-style public docstrings.
- [ ] Behavior/regression tests cover the change at the appropriate boundary.
- [ ] Targeted Ruff, Mypy, and Pytest checks pass.
- [ ] The complete quality gate passes without weakened controls.
- [ ] Dependency changes include necessity, vulnerability, maintenance, provenance, and license
      review.
- [ ] A material architectural decision has an ADR, or the PR explains why none is needed.
