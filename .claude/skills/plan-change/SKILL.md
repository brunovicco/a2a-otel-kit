---
name: plan-change
description: Create an evidence-based implementation plan before a non-trivial Python change.
argument-hint: "[change request]"
disable-model-invocation: true
context: fork
agent: planner
---

Plan this change without editing files:

$ARGUMENTS

Inspect the repository and return the plan format required by the planner agent. Highlight assumptions that materially affect implementation.
