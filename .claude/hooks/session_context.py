#!/usr/bin/env python3
"""Inject a small, non-sensitive Git summary at session start."""

from _common import emit_hook_output, project_root, read_input, run


def main() -> None:
    """Collect safe repository context and add it to the session."""
    payload = read_input()
    root = project_root(payload)

    branch = run(["git", "branch", "--show-current"], root).stdout.strip() or "detached"
    status_result = run(["git", "status", "--short"], root)
    changed = [line for line in status_result.stdout.splitlines() if line.strip()]
    preview = changed[:20]
    extra = len(changed) - len(preview)

    lines = [
        f"Project root: {root}",
        f"Current Git branch: {branch}",
        f"Working tree entries: {len(changed)}",
    ]
    if preview:
        lines.append("Changed files (status only; no contents):")
        lines.extend(f"- {line}" for line in preview)
    if extra > 0:
        lines.append(f"- ... and {extra} more")

    if not (root / "uv.lock").exists():
        lines.append(
            "uv.lock is missing. Generate and review it before relying on frozen installs."
        )

    emit_hook_output("SessionStart", additionalContext="\n".join(lines), sessionTitle=branch)


if __name__ == "__main__":
    main()
