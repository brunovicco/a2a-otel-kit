#!/usr/bin/env python3
"""Run the project-owned quality gate from one executable entry point."""

import argparse
import glob
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Check:
    """One named quality command."""

    name: str
    command: tuple[str, ...]


def load_settings(root: Path) -> dict[str, object]:
    """Load harness quality settings from pyproject.toml."""
    with (root / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)
    return project.get("tool", {}).get("engineering-harness", {}).get("quality", {})


def expand_roots(root: Path, patterns: list[str]) -> list[str]:
    """Expand configured roots and retain only existing paths."""
    found: set[str] = set()
    for pattern in patterns:
        matches = glob.glob(str(root / pattern))
        for match in matches:
            path = Path(match)
            if path.exists():
                found.add(path.relative_to(root).as_posix())
    return sorted(found)


def configured_checks(root: Path) -> list[Check]:
    """Build commands from project-owned source and test roots."""
    settings = load_settings(root)
    source_patterns = [str(item) for item in settings.get("source-roots", ["src"])]
    test_patterns = [str(item) for item in settings.get("test-roots", ["tests"])]
    source_roots = expand_roots(root, source_patterns)
    test_roots = expand_roots(root, test_patterns)
    type_roots = [*source_roots, *test_roots]

    checks = [
        Check("lock", ("uv", "lock", "--check")),
        Check("lint", ("ruff", "check", ".")),
        Check("format", ("ruff", "format", "--check", ".")),
        Check("architecture", (sys.executable, "scripts/validate_architecture.py")),
        Check("mcp", (sys.executable, "scripts/validate_mcp_config.py")),
    ]
    checks.append(Check("typing", ("mypy", *type_roots) if type_roots else ()))
    checks.append(Check("tests", ("pytest",) if test_roots else ()))
    checks.append(
        Check(
            "security",
            ("bandit", "-c", "pyproject.toml", "-r", *source_roots) if source_roots else (),
        )
    )
    checks.append(Check("dependencies", ("pip-audit",)))
    return checks


def parse_args() -> argparse.Namespace:
    """Parse quality-gate selection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="append", help="Run only this named check; repeatable")
    parser.add_argument("--list", action="store_true", help="List checks without running them")
    return parser.parse_args()


def main() -> int:
    """Run selected checks, continuing to provide complete evidence."""
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    checks = configured_checks(root)
    available = {check.name for check in checks}
    requested = set(args.check or available)
    unknown = sorted(requested - available)
    if unknown:
        print(f"Unknown or inapplicable checks: {', '.join(unknown)}", file=sys.stderr)
        print(f"Available checks: {', '.join(check.name for check in checks)}", file=sys.stderr)
        return 2
    selected = [check for check in checks if check.name in requested]
    if args.list:
        for check in selected:
            command = " ".join(check.command) if check.command else "skipped (no configured roots)"
            print(f"{check.name}: {command}")
        return 0

    failures: list[str] = []
    for check in selected:
        if not check.command:
            print(f"\n==> {check.name}: skipped (no configured roots)", flush=True)
            continue
        print(f"\n==> {check.name}: {' '.join(check.command)}", flush=True)
        result = subprocess.run(check.command, cwd=root, check=False)  # noqa: S603
        if result.returncode:
            failures.append(check.name)
    if failures:
        print(f"\nQuality gate failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("\nQuality gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
