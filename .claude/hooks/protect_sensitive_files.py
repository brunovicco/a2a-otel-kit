#!/usr/bin/env python3
"""Block Claude Code from reading or modifying sensitive files."""

import fnmatch
from pathlib import Path
from typing import Any

from _common import deny_tool, log_event, project_root, read_input, run_pre_tool_hook

DENIED_PATTERNS = (
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "**/secrets/**",
    "**/credentials/**",
    "**/.ssh/**",
    "**/.aws/**",
    "**/.azure/**",
    "**/.config/gcloud/**",
    "**/*.pem",
    "**/*.key",
    "**/id_rsa",
    "**/id_ed25519",
    "**/*credentials*.json",
    "**/*secret*.json",
    "**/terraform.tfstate*",
)

ALLOWED_EXAMPLES = (
    ".env.example",
    "**/.env.example",
    "**/*credentials*.example.*",
    "**/*secret*.example.*",
)


def strings(value: Any) -> list[str]:
    """Collect string values recursively from tool input."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for key, nested in value.items():
            if key in {"file_path", "path", "notebook_path", "filename"}:
                result.extend(strings(nested))
        return result
    if isinstance(value, list):
        result = []
        for nested in value:
            result.extend(strings(nested))
        return result
    return []


def matches(path: str) -> bool:
    """Return whether a path matches a denied pattern and is not an example."""
    normalized = path.replace("\\", "/")
    if any(fnmatch.fnmatch(normalized, pattern) for pattern in ALLOWED_EXAMPLES):
        return False
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in DENIED_PATTERNS)


def main() -> None:
    """Deny tool use for sensitive file paths."""
    payload = read_input()
    root = project_root(payload)
    tool_input = payload.get("tool_input", {})

    for raw in strings(tool_input):
        candidate = Path(raw).expanduser()
        display = raw
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            relative = candidate.resolve().relative_to(root).as_posix()
            display = relative
        except ValueError:
            display = candidate.as_posix()

        if matches(display) or matches(candidate.as_posix()):
            log_event(payload, "protect_sensitive_files", "sensitive-file", "deny")
            deny_tool(
                f"Access to sensitive path {raw!r} is blocked. "
                "Use an example file or an environment-variable name without secret values."
            )
            return


if __name__ == "__main__":
    run_pre_tool_hook(main)
