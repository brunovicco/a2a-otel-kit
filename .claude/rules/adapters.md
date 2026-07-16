---
paths:
  - "src/**/adapters/**/*.py"
---

# Adapter rules

- Every external call has an explicit timeout.
- Retries are bounded, observable, use exponential backoff with jitter, and target only transient errors.
- Preserve idempotency when retrying side-effecting operations.
- Do not leak vendor SDK types outside the adapter.
- Map external errors into application-owned errors.
- Keep Mypy strict. A localized ignore requires an error code, reason, ticket, and removal date.
- Repositories return and accept domain/application types, not ORM models.
- Add integration or contract tests for important adapter behavior.
