---
paths:
  - "src/**/*.py"
---

# Clean Architecture rules

- Preserve dependency direction: entrypoints -> application -> domain; adapters -> application/domain.
- Domain must not import Pydantic, web frameworks, ORMs, messaging clients, cloud SDKs, or concrete adapters.
- Define protocols on the consumer side, near the use case that needs them.
- Application services coordinate work; domain objects enforce business invariants.
- Translate Pydantic, ORM, SDK, and transport objects at boundaries.
- Translate infrastructure exceptions before they leave an adapter.
- Keep the composition root in or near the entrypoint.
- Add abstractions for demonstrated variation or isolation, not ritualistically.
- Do not move simple CRUD through unnecessary layers when no domain behavior exists.
