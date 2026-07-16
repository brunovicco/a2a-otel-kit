---
name: security-review
description: Perform a focused security and privacy review of the current changes.
disable-model-invocation: true
context: fork
agent: security-reviewer
---

Review the current diff and affected data flows for security, privacy, supply-chain, idempotency, timeout, retry, and logging risks. Run available deterministic checks and separate confirmed findings from hypotheses.
