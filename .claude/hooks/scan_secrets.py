#!/usr/bin/env python3
"""Detect high-confidence secrets in files just written by Claude Code."""

import re
from pathlib import Path
from typing import Any

from _common import (
    block_action,
    log_event,
    path_within,
    project_root,
    read_input,
    run_blocking_check,
)

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("OpenAI API key", re.compile(r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{32,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
)


def file_path(tool_input: Any) -> str | None:
    """Extract a file path from an Edit or Write tool payload."""
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return None


def findings_for_file(path: Path) -> list[str]:
    """Return high-confidence secret categories found in a regular project file."""
    if not path.is_file() or path.stat().st_size > 2_000_000:
        return []
    if path.name.endswith(".example") or ".example." in path.name:
        return []
    content = path.read_text(encoding="utf-8", errors="ignore")
    return [name for name, pattern in PATTERNS if pattern.search(content)]


def main() -> None:
    """Block continuation when a high-confidence secret appears in a changed file."""
    payload = read_input()
    root = project_root(payload)
    raw = file_path(payload.get("tool_input"))
    if raw is None:
        return

    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    if not path_within(path, root):
        return
    findings = findings_for_file(path)
    if findings:
        log_event(payload, "scan_secrets", "secret-in-file", "block")
        block_action(
            f"Potential secret detected in {path.relative_to(root).as_posix()!r}: "
            f"{', '.join(findings)}. Remove it and rotate it if real. "
            "Use a secret manager or environment-variable placeholder."
        )


if __name__ == "__main__":
    run_blocking_check(main, check_name="Secret scan")
