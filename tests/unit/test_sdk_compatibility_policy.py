import importlib.util
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
