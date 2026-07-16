# Git and collaboration rules

- Do not commit, push, merge, rebase shared branches, publish, or deploy without an explicit request.
- Do not use `--force`, `reset --hard`, or destructive clean operations.
- Keep changes focused and avoid unrelated formatting or refactoring.
- Read the complete diff before proposing completion.
- Commit and PR text is in English and explains intent rather than mechanics.
- Never bypass a failing gate by weakening configuration without explicit approval.
- Review `.claude/agent-memory/` diffs like any other change before committing; it is agent-written content, not human-authored, and must not carry secrets or personal data.
