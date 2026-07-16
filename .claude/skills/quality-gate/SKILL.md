---
name: quality-gate
description: Run the complete Python quality gate and summarize failures without changing configuration.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash
---

Run the project-owned gate with `uv run python scripts/quality_gate.py`. Use `--list` and named
`--check` selections only when focused evidence is requested.

Do not edit files or weaken settings. Report command, status, key errors, whether each failure is related to the current diff, and the final gate result.
