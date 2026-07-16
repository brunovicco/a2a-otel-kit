---
paths:
  - "**/*.py"
  - "pyproject.toml"
---

# Python implementation rules

- Use absolute imports ordered by Ruff: standard library, third-party, local.
- Do not use `from __future__ import annotations`. The supported Python versions evaluate modern
  annotation syntax natively; quote only the individual forward references that require deferred
  evaluation.
- Public functions and non-trivial private functions require complete type hints.
- Do not introduce `Any` beyond a boundary; parse it immediately into a known type.
- Public modules, classes, protocols, methods, and functions use Google-style docstrings.
- Prefer immutable `@dataclass(frozen=True, slots=True)` Value Objects in the domain.
- Use `Decimal` for monetary values and timezone-aware UTC datetimes.
- Raise meaningful domain or application errors and preserve causes with `raise ... from exc`.
- Never use `except Exception: pass` or mutable default arguments.
- Keep functions cohesive; extract complexity when it improves meaning or testability.
- Avoid utility dumping grounds and vague names such as `Manager`, `Helper`, or `Common`.
