---
name: create-adr
description: Create an Architecture Decision Record for a material engineering decision.
argument-hint: "[decision topic]"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Edit, Write
---

Create the next numbered ADR under `docs/adr/` for:

$ARGUMENTS

Use sections: Status, Date, Context, Decision, Alternatives considered, Consequences, Security and privacy impact, Operational impact, and Follow-up. Ground it in the current repository and avoid inventing decisions not provided or evidenced.
