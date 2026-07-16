---
name: review-mcp
description: Review MCP configuration, permissions, authentication, data egress, and prompt-injection exposure without connecting to servers.
disable-model-invocation: true
context: fork
agent: mcp-integrator
---

Review the repository MCP configuration without authenticating or invoking external MCP tools.

Check scope, transport, endpoint trust, dependency pinning, credentials, least privilege, write capabilities, production access, PII, prompt injection, timeout, auditability, managed-policy compatibility, and documentation. Run `uv run python scripts/validate_mcp_config.py` and return evidence-backed findings ordered by severity.
