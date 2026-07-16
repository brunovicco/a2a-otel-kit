#!/usr/bin/env python3
"""Render a compact Claude Code status line."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def get(value: Any, *keys: str, default: Any = "") -> Any:
    """Read nested dictionaries safely."""
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def branch(cwd: str) -> str:
    """Return the current Git branch without raising."""
    git = shutil.which("git")
    if git is None:
        return "-"
    try:
        result = subprocess.run(  # noqa: S603 -- executable is resolved with shutil.which.
            [git, "branch", "--show-current"],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return "-"
    return result.stdout.strip() or "detached"


def main() -> None:
    """Read Claude status JSON from stdin and print one line."""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    model = get(payload, "model", "display_name", default="Claude")
    cwd = str(get(payload, "workspace", "current_dir", default="."))
    percent = get(payload, "context_window", "used_percentage", default=0)
    cost = get(payload, "cost", "total_cost_usd", default=None)
    name = Path(cwd).name or cwd

    suffix = f" | ${cost:.3f}" if isinstance(cost, (int, float)) else ""
    print(f"[{model}] {name} | {branch(cwd)} | {float(percent):.0f}% context{suffix}")


if __name__ == "__main__":
    main()
