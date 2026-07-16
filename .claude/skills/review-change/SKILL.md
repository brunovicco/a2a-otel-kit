---
name: review-change
description: Review the current branch diff for correctness, architecture, maintainability, and missing tests.
disable-model-invocation: true
context: fork
agent: architecture-reviewer
---

Review the current branch diff and relevant surrounding code. Rank material findings by severity, deduplicate them, and include concrete evidence and remediation.
