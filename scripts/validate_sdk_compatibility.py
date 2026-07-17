"""Validate that optional SDK and development dependency bounds remain aligned."""

import re
import tomllib
from pathlib import Path


def _requirement_by_name(requirements: list[str], name: str) -> str:
    """Return one normalized requirement string selected by distribution name."""
    matches = [item for item in requirements if item.split("[", 1)[0].split(">", 1)[0] == name]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} requirement")
    return matches[0]


def _bounds(requirement: str) -> str:
    """Extract the comparator portion from a simple direct requirement."""
    match = re.search(r"[<>=]", requirement)
    if match is None:
        return ""
    return requirement[match.start() :]


def validate(pyproject_path: Path) -> None:
    """Reject optional/development SDK bounds that no longer describe the same interval."""
    with pyproject_path.open("rb") as handle:
        document = tomllib.load(handle)
    optional = document["project"]["optional-dependencies"]
    development = document["dependency-groups"]["dev"]
    for name in ("a2a-sdk", "mcp"):
        extra = "a2a" if name == "a2a-sdk" else "mcp"
        public_requirement = _requirement_by_name(optional[extra], name)
        development_requirement = _requirement_by_name(development, name)
        public_bounds = _bounds(public_requirement)
        development_bounds = _bounds(development_requirement)
        if public_bounds != development_bounds:
            raise ValueError(f"{name} optional and development bounds differ")
        if not public_bounds.startswith(">=") or ",<" not in public_bounds:
            raise ValueError(f"{name} must declare both minimum and exclusive upper bounds")


if __name__ == "__main__":
    validate(Path(__file__).resolve().parents[1] / "pyproject.toml")
