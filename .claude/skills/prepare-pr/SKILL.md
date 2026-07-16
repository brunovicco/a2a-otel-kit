---
name: prepare-pr
description: Verify a branch and draft a reviewable pull-request description without publishing it.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash
---

Prepare a pull request for the current branch.

1. Read the complete diff against the base branch.
2. Run `/quality-gate` or equivalent deterministic checks.
3. Identify behavior, architecture, security, privacy, migration, and operational impact.
4. Produce an English PR title and body with:
   - Problem
   - Solution
   - Main changes
   - Test evidence
   - Security and data impact
   - Operational and rollout impact
   - Risks and follow-ups
5. Do not create, push, or publish the PR unless the user explicitly asks.
