#!/usr/bin/env python3
"""Guard outbound MCP calls against secrets and uncontrolled mutations."""

import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from _common import ask_tool, deny_tool, log_event, read_input, run_pre_tool_hook

MUTATING_TERMS = {
    "add",
    "approve",
    "archive",
    "assign",
    "cancel",
    "close",
    "commit",
    "create",
    "delete",
    "deploy",
    "disable",
    "enable",
    "execute",
    "forward",
    "grant",
    "import",
    "invite",
    "merge",
    "modify",
    "move",
    "patch",
    "pay",
    "post",
    "publish",
    "put",
    "push",
    "remove",
    "rename",
    "reply",
    "restart",
    "restore",
    "revoke",
    "run",
    "send",
    "set",
    "start",
    "stop",
    "submit",
    "transfer",
    "trigger",
    "update",
    "upsert",
    "upload",
    "write",
}

SECRET_ACCESS_TERMS = {
    "credential",
    "credentials",
    "private_key",
    "secret",
    "secrets",
    "token",
    "tokens",
}

SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|credential|password|passwd|private[_-]?key|secret|token|api[_-]?key)",
    re.IGNORECASE,
)

HIGH_CONFIDENCE_SECRET = re.compile(
    r"(?:"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"AKIA[0-9A-Z]{16}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}"
    r")"
)

SAFE_PLACEHOLDER = re.compile(
    r"^(?:\$\{[A-Z_][A-Z0-9_]*(?::-.*)?\}|<[^>]+>|REDACTED|MASKED|\*{4,})$",
    re.IGNORECASE,
)


def iter_values(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Yield scalar values from an arbitrarily nested tool input."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            yield from iter_values(child, (*path, key_text))
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            yield from iter_values(child, (*path, str(index)))
        return
    yield path, value


def tool_terms(tool_name: str) -> set[str]:
    """Return normalized terms from an MCP tool name."""
    leaf = tool_name.rsplit("__", maxsplit=1)[-1]
    leaf = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", leaf)
    return {term for term in re.split(r"[^a-z0-9]+", leaf.lower()) if term}


def contains_literal_secret(tool_input: Mapping[str, Any]) -> str | None:
    """Return a reason when outbound MCP input appears to contain a secret."""
    for path, value in iter_values(tool_input):
        if not isinstance(value, str) or not value:
            continue
        if HIGH_CONFIDENCE_SECRET.search(value):
            return f"high-confidence secret detected at {'.'.join(path) or '<root>'}"
        key = path[-1] if path else ""
        if SENSITIVE_KEY.search(key) and not SAFE_PLACEHOLDER.fullmatch(value.strip()):
            return f"literal sensitive value detected at {'.'.join(path)}"
    return None


def targets_production(tool_input: Mapping[str, Any]) -> bool:
    """Return whether tool input appears to target production."""
    for path, value in iter_values(tool_input):
        if not isinstance(value, str):
            continue
        key = path[-1].lower() if path else ""
        production_keys = {
            "account",
            "cluster",
            "database",
            "env",
            "environment",
            "host",
            "instance",
            "namespace",
            "project",
            "stage",
            "target",
            "url",
        }
        if key in production_keys and re.search(
            r"(?:^|[-_.:/])prod(?:uction)?(?:$|[-_.:/])",
            value,
            re.IGNORECASE,
        ):
            return True
    return False


def main() -> None:
    """Classify an MCP call and force safe permission behavior."""
    payload = read_input()
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_name, str) or not tool_name.startswith("mcp__"):
        return
    if not isinstance(tool_input, Mapping):
        tool_input = {}

    secret_reason = contains_literal_secret(tool_input)
    if secret_reason:
        log_event(payload, "guard_mcp", "mcp-secret", "deny")
        deny_tool(
            f"Blocked MCP call: {secret_reason}. Use OAuth or environment references instead."
        )
        return

    terms = tool_terms(tool_name)
    if terms & SECRET_ACCESS_TERMS:
        log_event(payload, "guard_mcp", "mcp-secret-access", "deny")
        deny_tool(
            "Blocked MCP secret or credential access. Retrieve credentials outside Claude Code."
        )
        return

    if terms & MUTATING_TERMS:
        production = targets_production(tool_input)
        if production:
            log_event(payload, "guard_mcp", "mcp-mutation-production", "deny")
            deny_tool(
                "Blocked MCP mutation against a production target. "
                "Use the approved production change workflow outside this harness."
            )
            return
        reason = "MCP tool can change external state and requires explicit human confirmation."
        log_event(
            payload,
            "guard_mcp",
            "mcp-mutation",
            "ask",
        )
        ask_tool(reason)


if __name__ == "__main__":
    run_pre_tool_hook(main)
