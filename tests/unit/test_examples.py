import runpy
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.parametrize("filename", ["a2a_adoption.py", "mcp_adoption.py"])
def test_adoption_example_imports_without_side_effects(filename: str) -> None:
    namespace = runpy.run_path(str(EXAMPLES / filename), run_name="adoption_example")

    assert any(name.startswith("instrument_") for name in namespace)
