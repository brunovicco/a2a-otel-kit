# Claude Code project harness

## Component responsibilities

- `../CLAUDE.md`: minimal always-on Claude-specific instructions.
- `../AGENTS.md`: cross-agent engineering contract.
- `rules/`: modular standards, with path-scoped loading where useful.
- `skills/`: repeatable procedures invoked with `/name`.
- `agents/`: specialized workers with constrained tools and prompts.
- `hooks/`: deterministic safety and automation scripts, including a changed-file secret scan
  before Claude stops.
- `workflows/`: scripted multi-agent orchestration for larger tasks.
- `output-styles/`: response and reporting conventions.
- `settings.json`: permissions, hooks, environment, and shared defaults.
- `../.mcp.json.example`: opt-in project MCP configuration without credentials.
- `../docs/MCP.md`: MCP architecture, approval, authentication, and enterprise controls.

Run `/memory`, `/hooks`, `/context`, `/doctor`, and `/mcp` to inspect what Claude Code loaded.
