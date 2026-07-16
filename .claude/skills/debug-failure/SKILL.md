---
name: debug-failure
description: Investigate a failure and return an evidence-based root-cause analysis.
argument-hint: "[failure, command, or symptom]"
disable-model-invocation: true
context: fork
agent: debugger
---

Investigate this failure without masking it:

$ARGUMENTS

Reproduce it, compare hypotheses, identify the root cause, and propose the smallest safe fix and regression test.
