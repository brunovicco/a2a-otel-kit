#!/usr/bin/env python3
"""Enforce configurable package boundaries and optional Clean Architecture layers."""

import ast
import glob
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LAYERS = {"domain", "application", "adapters", "entrypoints"}
FORBIDDEN_LOCAL: dict[str, set[str]] = {
    "domain": {"application", "adapters", "entrypoints"},
    "application": {"adapters", "entrypoints"},
}
FORBIDDEN_EXTERNAL: dict[str, tuple[str, ...]] = {
    "domain": (
        "boto3",
        "botocore",
        "celery",
        "django",
        "fastapi",
        "flask",
        "httpx",
        "kafka",
        "pydantic",
        "redis",
        "requests",
        "sqlalchemy",
    ),
    "application": (
        "boto3",
        "botocore",
        "celery",
        "django",
        "fastapi",
        "flask",
        "httpx",
        "kafka",
        "redis",
        "requests",
        "sqlalchemy",
    ),
}
DYNAMIC_IMPORTS = {"__import__", "importlib.import_module"}


@dataclass(frozen=True, slots=True)
class Violation:
    """Represent one architecture dependency violation."""

    path: Path
    line: int
    message: str


@dataclass(frozen=True, slots=True)
class Boundary:
    """A default-deny import policy rooted at one package path."""

    path: Path
    allowed_imports: tuple[str, ...]
    deny_dynamic_imports: bool


def layer_for(path: Path) -> str | None:
    """Return the architectural layer represented in a source path."""
    if len(path.parts) < 2:
        return None
    layer = path.parts[1]
    return layer if layer in LAYERS else None


def imported_modules(tree: ast.AST, current_module: tuple[str, ...]) -> list[tuple[int, str]]:
    """Collect absolute module names from import statements."""
    imports: list[tuple[int, str]] = []
    current_package = current_module[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        module_parts = tuple((node.module or "").split(".")) if node.module else ()
        if node.level:
            retained = max(0, len(current_package) - (node.level - 1))
            target_parts = current_package[:retained] + module_parts
        else:
            target_parts = module_parts
        base = ".".join(part for part in target_parts if part)
        for alias in node.names:
            imports.append((node.lineno, ".".join(part for part in (base, alias.name) if part)))
    return sorted(imports)


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
        return f"{call.func.value.id}.{call.func.attr}"
    return None


def validate_file(path: Path, src_root: Path) -> list[Violation]:
    """Validate legacy Clean Architecture imports for one Python source file."""
    relative = path.relative_to(src_root)
    layer = layer_for(relative)
    if layer not in FORBIDDEN_LOCAL:
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        return [Violation(relative, getattr(exc, "lineno", 1) or 1, f"cannot parse file: {exc}")]
    module = relative.with_suffix("").parts
    package = module[0]
    violations: list[Violation] = []
    for line, imported in imported_modules(tree, module):
        parts = imported.split(".") if imported else []
        if len(parts) > 1 and parts[0] == package and parts[1] in FORBIDDEN_LOCAL[layer]:
            violations.append(
                Violation(
                    relative,
                    line,
                    f"{layer} must not depend on local layer {parts[1]!r}: {imported}",
                )
            )
            continue
        prefix = imported.split(".", maxsplit=1)[0]
        if prefix in FORBIDDEN_EXTERNAL[layer]:
            violations.append(
                Violation(
                    relative,
                    line,
                    f"{layer} must not import infrastructure package {prefix!r}: {imported}",
                )
            )
    return violations


def _is_allowed(module: str, allowed: tuple[str, ...]) -> bool:
    prefix = module.split(".", maxsplit=1)[0]
    if "stdlib" in allowed and prefix in sys.stdlib_module_names:
        return True
    return any(
        module == item or module.startswith(item + ".") for item in allowed if item != "stdlib"
    )


def validate_boundary_file(path: Path, root: Path, boundary: Boundary) -> list[Violation]:
    """Apply one default-deny package policy."""
    relative = path.relative_to(root)
    module = path.relative_to(boundary.path).with_suffix("").parts
    package = boundary.path.name
    current_module = (package, *module)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        return [
            Violation(
                relative,
                getattr(exc, "lineno", 1) or 1,
                f"cannot parse module {'.'.join(current_module)}: {exc}",
            )
        ]
    violations = [
        Violation(
            relative, line, f"module {'.'.join(current_module)} imports denied module {imported!r}"
        )
        for line, imported in imported_modules(tree, current_module)
        if imported and not _is_allowed(imported, boundary.allowed_imports)
    ]
    if boundary.deny_dynamic_imports:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) in DYNAMIC_IMPORTS:
                module_name = ".".join(current_module)
                call_name = _call_name(node)
                violations.append(
                    Violation(
                        relative,
                        node.lineno,
                        f"module {module_name} uses denied dynamic import {call_name!r}",
                    )
                )
    return sorted(violations, key=lambda item: (item.path.as_posix(), item.line, item.message))


def load_config(root: Path) -> tuple[list[Path], bool, list[Boundary]]:
    """Load source roots and boundaries from pyproject.toml."""
    with (root / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)
    config: dict[str, Any] = (
        project.get("tool", {}).get("engineering-harness", {}).get("architecture", {})
    )
    patterns = [str(item) for item in config.get("source-roots", ["src"])]
    source_roots = sorted(
        {
            Path(match).resolve()
            for pattern in patterns
            for match in glob.glob(str(root / pattern))
            if Path(match).is_dir()
        }
    )
    clean = bool(config.get("clean-architecture", False))
    boundaries: list[Boundary] = []
    for item in config.get("boundaries", []):
        boundary_path = (root / str(item["path"])).resolve()
        try:
            boundary_path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"architecture boundary escapes project: {item['path']}") from exc
        boundaries.append(
            Boundary(
                path=boundary_path,
                allowed_imports=tuple(
                    str(value) for value in item.get("allowed-imports", ["stdlib"])
                ),
                deny_dynamic_imports=bool(item.get("deny-dynamic-imports", True)),
            )
        )
    return source_roots, clean, boundaries


def main() -> int:
    """Validate configured source modules and return a process status."""
    root = Path(__file__).resolve().parents[1]
    try:
        source_roots, clean, boundaries = load_config(root)
    except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"Invalid architecture configuration: {exc}", file=sys.stderr)
        return 2
    violations: list[Violation] = []
    if clean:
        for source_root in source_roots:
            violations.extend(
                violation
                for path in sorted(source_root.rglob("*.py"))
                for violation in validate_file(path, source_root)
            )
    for boundary in boundaries:
        if not boundary.path.is_dir():
            display_path = boundary.path.relative_to(root)
            print(
                f"Configured architecture boundary does not exist: {display_path}",
                file=sys.stderr,
            )
            return 2
        violations.extend(
            violation
            for path in sorted(boundary.path.rglob("*.py"))
            for violation in validate_boundary_file(path, root, boundary)
        )
    violations.sort(key=lambda item: (item.path.as_posix(), item.line, item.message))
    if not violations:
        summary = f"{len(source_roots)} source roots, {len(boundaries)} boundaries"
        print(f"Architecture dependency check passed ({summary}).")
        return 0
    print("Architecture dependency violations:", file=sys.stderr)
    for violation in violations:
        print(f"- {violation.path}:{violation.line}: {violation.message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
