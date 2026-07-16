---
name: implement-change
description: Implement an accepted, focused Python change with tests and verification.
argument-hint: "[accepted change or plan]"
disable-model-invocation: true
context: fork
agent: python-implementer
---

Implement the following accepted change:

$ARGUMENTS

Keep the diff focused, follow project rules, add tests, and run targeted checks. Do not commit or push.
