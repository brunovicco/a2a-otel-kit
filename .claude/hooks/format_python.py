#!/usr/bin/env python3
"""Run Ruff safely on a Python file changed by Claude Code."""

import shutil
from pathlib import Path
from typing import Any

from _common import emit_hook_output, path_within, project_root, read_input, run


def file_path(tool_input: Any) -> str | None:
    """Extract the target path from a write-like tool payload."""
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return None


def main() -> None:
    """Format one changed Python file without mutating unrelated files."""
    payload = read_input()
    root = project_root(payload)
    raw = file_path(payload.get("tool_input"))
    if raw is None or not raw.endswith(".py"):
        return

    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    if not path_within(path, root) or not path.is_file():
        return
    if shutil.which("uv") is None or not (root / "pyproject.toml").exists():
        return

    relative = str(path.relative_to(root))
    frozen = ["--frozen"] if (root / "uv.lock").exists() else []
    commands = (
        ["uv", "run", *frozen, "ruff", "check", "--fix", relative],
        ["uv", "run", *frozen, "ruff", "format", relative],
    )

    errors: list[str] = []
    for command in commands:
        result = run(command, root, timeout=45)
        if result.returncode != 0:
            output = (result.stderr or result.stdout).strip()
            errors.append(f"{' '.join(command)} failed: {output[:2000]}")

    if errors:
        emit_hook_output(
            "PostToolUse",
            additionalContext="Ruff could not complete for the changed file:\n" + "\n".join(errors),
        )


if __name__ == "__main__":
    main()
