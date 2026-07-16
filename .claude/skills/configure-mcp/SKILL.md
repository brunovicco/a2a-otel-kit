---
name: configure-mcp
description: Configure an explicitly requested Claude Code MCP integration using the project security policy.
argument-hint: "[system, endpoint, authentication method, and required capabilities]"
disable-model-invocation: true
context: fork
agent: mcp-integrator
---

Configure or update the MCP integration described below:

$ARGUMENTS

Do not guess missing endpoints or credentials. Prefer a local-scope trial before recommending project scope. Keep all secrets outside version control, document required environment-variable names, inventory read and write tools, and run the MCP configuration validator.
