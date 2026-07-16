# ADR-0001: Adopt Clean Architecture dependency boundaries

- Status: Accepted
- Date: YYYY-MM-DD

## Context

The service requires business rules to remain independent from web frameworks, persistence, messaging, and external SDKs.

## Decision

Use the dependency direction documented in `docs/ARCHITECTURE.md` and enforce it through package structure, review, tests, and import-contract tooling when introduced.

## Consequences

- Domain code remains independently testable.
- Boundary translation is explicit.
- Small CRUD features should not receive unnecessary abstraction.
- More mapping code is accepted where it protects domain semantics.
