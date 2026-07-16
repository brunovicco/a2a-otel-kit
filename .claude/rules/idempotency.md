---
paths:
  - "src/**/*command*.py"
  - "src/**/*consumer*.py"
  - "src/**/*handler*.py"
  - "src/**/*payment*.py"
  - "src/**/*transfer*.py"
---

# Idempotency rules

- Define the business effect that must remain single before writing code.
- Bind the idempotency key to operation, actor or tenant, and normalized payload hash.
- The same key and payload return the prior result; a different payload is rejected.
- Make check, business mutation, and result persistence atomic when possible.
- Use database uniqueness before distributed locks when the database can guarantee consistency.
- Assume at-least-once message delivery.
- Acknowledge a message only after required processing is durable.
- Use transactional outbox when state change and event publication must be consistent.
