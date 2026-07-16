---
paths:
  - "tests/**/*.py"
  - "src/**/*.py"
---

# Testing rules

- Test observable behavior and business invariants, not private implementation details.
- Bug fixes include a regression test that fails before the fix.
- Unit tests isolate network, database, queue, filesystem, clock, randomness, and identifiers.
- Integration tests use real adapters or realistic infrastructure.
- Contract tests protect message, API, repository, and provider contracts.
- Critical side effects test duplicate delivery, concurrent requests, retries, timeouts, and partial failures.
- Avoid sleep-based synchronization and flaky retry loops in tests.
- Name tests as behavior: `test_<result>_when_<condition>` where practical.
- Do not weaken assertions only to make a failing test pass.
