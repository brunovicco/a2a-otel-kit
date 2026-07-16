#!/usr/bin/env python3
"""Scan every changed or untracked project file before Claude stops."""

from pathlib import Path

from _common import (
    block_action,
    log_event,
    path_within,
    project_root,
    read_input,
    run,
    run_blocking_check,
)
from scan_secrets import findings_for_file


def changed_paths(root: Path) -> set[Path]:
    """Return tracked changes, staged changes, and untracked files without shell parsing."""
    repository = run(["git", "rev-parse", "--is-inside-work-tree"], root)
    if repository.returncode != 0 or repository.stdout.strip() != "true":
        return set()
    commands = (
        ["git", "diff", "--name-only", "-z"],
        ["git", "diff", "--cached", "--name-only", "-z"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    )
    paths: set[Path] = set()
    for command in commands:
        result = run(command, root)
        if result.returncode != 0:
            raise RuntimeError(f"{' '.join(command)} failed")
        for raw in result.stdout.split("\0"):
            if raw:
                paths.add(root / raw)
    return paths


def main() -> None:
    """Stop the agent loop when any changed file contains a probable secret."""
    payload = read_input()
    root = project_root(payload)
    findings: list[str] = []
    for path in sorted(changed_paths(root)):
        if not path_within(path, root):
            continue
        categories = findings_for_file(path)
        if categories:
            relative = path.relative_to(root)
            findings.append(f"{relative.as_posix()!r}: {', '.join(categories)}")

    if findings:
        log_event(payload, "scan_worktree", "secret-in-worktree", "block")
        preview = "; ".join(findings[:10])
        suffix = f"; and {len(findings) - 10} more" if len(findings) > 10 else ""
        block_action(
            "Potential secrets remain in changed files: "
            f"{preview}{suffix}. Remove and rotate real credentials before continuing."
        )


if __name__ == "__main__":
    run_blocking_check(main, check_name="Changed-file secret scan")
