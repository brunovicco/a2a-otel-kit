---
paths:
  - "src/**/entrypoints/**/*.py"
  - "src/**/api/**/*.py"
  - "src/**/*schema*.py"
---

# API and boundary rules

- Validate external input with Pydantic and reject unknown fields when the contract is strict.
- Convert boundary schemas into commands, queries, or domain Value Objects explicitly.
- Do not return internal exceptions, stack traces, or infrastructure details.
- Use a stable error envelope and machine-readable error codes.
- Side-effecting POST operations require an idempotency strategy.
- Authentication and authorization decisions must be explicit and tested.
- Do not log complete requests or responses.
- Document backward compatibility and versioning impact for contract changes.
