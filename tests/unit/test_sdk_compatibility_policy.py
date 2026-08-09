import importlib.util
import tomllib
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_validator() -> ModuleType:
    path = REPO_ROOT / "scripts" / "validate_sdk_compatibility.py"
    spec = importlib.util.spec_from_file_location("validate_sdk_compatibility", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_optional_sdk_bounds_align_with_development_environment() -> None:
    _load_validator().validate(REPO_ROOT / "pyproject.toml")


def test_mcp_sdk_contract_targets_supported_v2_range() -> None:
    """The public extra and development environment both require the supported MCP 2.x line."""
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        document = tomllib.load(handle)

    assert document["project"]["optional-dependencies"]["mcp"] == ["mcp>=2.0,<3"]
    assert "mcp>=2.0,<3" in document["dependency-groups"]["dev"]
