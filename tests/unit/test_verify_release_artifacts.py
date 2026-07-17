"""Tests for scripts/verify_release_artifacts.py.

Wheel/sdist inspection is tested against synthetic archives built in ``tmp_path`` so these tests
stay network-free and independent of any real ``uv build`` output. The isolated-venv wheel
installs (base/``a2a``/``mcp``) require network access to resolve dependencies and are exercised
by CI running the script directly against a real build, not here. The network-blocking guard and
the "no optional SDK required" guarantee are tested directly against this interpreter, since both
only need the smoke-test mechanism itself, not a fresh venv.
"""

import hashlib
import importlib.util
import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType


def _load_module(name: str, relative_path: str) -> ModuleType:
    """Load a scripts/*.py module by file path; scripts/ is not an importable package."""
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(name, root / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = _load_module("verify_release_artifacts", "scripts/verify_release_artifacts.py")

VERSION = "9.9.9"
DIST_NAME = "a2a_otel_kit"


def _metadata_payload(*, version: str = VERSION, extras: tuple[str, ...] = ("a2a", "mcp")) -> bytes:
    """Build a minimal, well-formed METADATA/PKG-INFO payload."""
    lines = [
        "Metadata-Version: 2.4",
        "Name: a2a-otel-kit",
        f"Version: {version}",
        "License-Expression: MIT",
        "Requires-Python: >=3.13,<3.15",
        *[f"Provides-Extra: {extra}" for extra in extras],
        "",
        "A description of the package.",
    ]
    return "\n".join(lines).encode()


def _write_wheel(
    path: Path,
    *,
    include_py_typed: bool = True,
    extras: tuple[str, ...] = ("a2a", "mcp"),
    version: str = VERSION,
    include_metadata: bool = True,
) -> Path:
    """Write a synthetic, well-formed wheel with optional defects for negative tests."""
    wheel_path = path / f"{DIST_NAME}-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as archive:
        for module in verify.REQUIRED_MODULES:
            if module == "py.typed" and not include_py_typed:
                continue
            archive.writestr(f"{DIST_NAME}/{module}", "")
        if include_metadata:
            archive.writestr(
                f"{DIST_NAME}-{VERSION}.dist-info/METADATA",
                _metadata_payload(version=version, extras=extras),
            )
    return wheel_path


def _write_sdist(
    path: Path,
    *,
    missing: str | None = None,
    version: str = VERSION,
    extras: tuple[str, ...] = ("a2a", "mcp"),
) -> Path:
    """Write a synthetic, well-formed sdist with one optional omission for negative tests."""
    prefix = f"{DIST_NAME}-{VERSION}"
    sdist_path = path / f"{prefix}.tar.gz"
    with tarfile.open(sdist_path, "w:gz") as archive:

        def add(name: str, content: bytes = b"") -> None:
            if name == missing:
                return
            info = tarfile.TarInfo(name=f"{prefix}/{name}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))

        for required in verify.REQUIRED_SDIST_FILES:
            add(required)
        for module in verify.REQUIRED_MODULES:
            add(f"src/{DIST_NAME}/{module}")
        add("PKG-INFO", _metadata_payload(version=version, extras=extras))
    return sdist_path


def test_find_artifacts_fails_when_wheel_is_missing(tmp_path: Path) -> None:
    """No wheel in the directory is rejected even if the sdist is present."""
    _write_sdist(tmp_path)
    try:
        verify.find_artifacts(tmp_path)
    except SystemExit as exc:
        assert "wheel" in str(exc)
    else:
        raise AssertionError("expected SystemExit for a missing wheel")


def test_find_artifacts_fails_when_sdist_is_missing(tmp_path: Path) -> None:
    """No sdist in the directory is rejected even if the wheel is present."""
    _write_wheel(tmp_path)
    try:
        verify.find_artifacts(tmp_path)
    except SystemExit as exc:
        assert "sdist" in str(exc)
    else:
        raise AssertionError("expected SystemExit for a missing sdist")


def test_find_artifacts_succeeds_with_exactly_one_of_each(tmp_path: Path) -> None:
    """Exactly one wheel and one sdist resolve without error."""
    wheel_path = _write_wheel(tmp_path)
    sdist_path = _write_sdist(tmp_path)

    found_wheel, found_sdist = verify.find_artifacts(tmp_path)

    assert found_wheel == wheel_path
    assert found_sdist == sdist_path


def test_inspect_wheel_passes_for_a_well_formed_wheel(tmp_path: Path) -> None:
    """A wheel with every required module, py.typed, and matching metadata has no errors."""
    wheel_path = _write_wheel(tmp_path)

    assert verify.inspect_wheel(wheel_path, VERSION) == []


def test_inspect_wheel_reports_missing_py_typed(tmp_path: Path) -> None:
    """A wheel without py.typed is rejected."""
    wheel_path = _write_wheel(tmp_path, include_py_typed=False)

    errors = verify.inspect_wheel(wheel_path, VERSION)

    assert any("py.typed" in error for error in errors)


def test_inspect_wheel_reports_wrong_version(tmp_path: Path) -> None:
    """A wheel reporting a different version than expected is rejected."""
    wheel_path = _write_wheel(tmp_path, version=VERSION)

    errors = verify.inspect_wheel(wheel_path, "1.2.3")

    assert any("Version" in error for error in errors)


def test_inspect_wheel_reports_missing_extra(tmp_path: Path) -> None:
    """A wheel missing the mcp extra's Provides-Extra entry is rejected."""
    wheel_path = _write_wheel(tmp_path, extras=("a2a",))

    errors = verify.inspect_wheel(wheel_path, VERSION)

    assert any("Provides-Extra" in error and "mcp" in error for error in errors)


def test_inspect_sdist_passes_for_a_well_formed_sdist(tmp_path: Path) -> None:
    """An sdist with every required file, module, and matching metadata has no errors."""
    sdist_path = _write_sdist(tmp_path)

    assert verify.inspect_sdist(sdist_path, VERSION) == []


def test_inspect_sdist_reports_missing_license(tmp_path: Path) -> None:
    """An sdist without a LICENSE file is rejected."""
    sdist_path = _write_sdist(tmp_path, missing="LICENSE")

    errors = verify.inspect_sdist(sdist_path, VERSION)

    assert any("LICENSE" in error for error in errors)


def test_inspect_sdist_reports_wrong_version(tmp_path: Path) -> None:
    """An sdist reporting a different version than expected is rejected."""
    sdist_path = _write_sdist(tmp_path, version=VERSION)

    errors = verify.inspect_sdist(sdist_path, "1.2.3")

    assert any("Version" in error for error in errors)


def test_inspect_sdist_reports_missing_extra(tmp_path: Path) -> None:
    """An sdist missing the a2a extra's Provides-Extra entry is rejected."""
    sdist_path = _write_sdist(tmp_path, extras=("mcp",))

    errors = verify.inspect_sdist(sdist_path, VERSION)

    assert any("Provides-Extra" in error and "a2a" in error for error in errors)


def test_hash_and_size_matches_actual_file_contents(tmp_path: Path) -> None:
    """The reported hash and size correspond to the file's real bytes."""

    target = tmp_path / "artifact.bin"
    target.write_bytes(b"release bytes")

    digest, size = verify.hash_and_size(target)

    assert digest == hashlib.sha256(b"release bytes").hexdigest()
    assert size == len(b"release bytes")


def test_smoke_test_import_succeeds_for_the_base_package() -> None:
    """The base package imports cleanly under the network-blocking guard."""
    failure = verify.smoke_test_import(Path(sys.executable), "import a2a_otel_kit")

    assert failure is None


def test_smoke_test_import_blocks_network_io() -> None:
    """An import path that opens a socket is caught by the guard, not silently allowed."""
    failure = verify.smoke_test_import(
        Path(sys.executable),
        "import socket; socket.socket().connect(('127.0.0.1', 1))",
    )

    assert failure is not None
    assert "network I/O attempted" in failure


def test_base_package_import_does_not_require_optional_sdks() -> None:
    """Importing a2a_otel_kit succeeds even when the optional SDKs cannot be imported."""
    guard = (
        "import builtins\n"
        "_real_import = builtins.__import__\n"
        "def _guarded(name, *args, **kwargs):\n"
        "    if name in ('a2a', 'mcp') or name.startswith(('a2a.', 'mcp.')):\n"
        "        raise ImportError(f'optional SDK {name} must not be required by base import')\n"
        "    return _real_import(name, *args, **kwargs)\n"
        "builtins.__import__ = _guarded\n"
    )
    failure = verify.smoke_test_import(Path(sys.executable), f"{guard}\nimport a2a_otel_kit")

    assert failure is None


def test_current_build_passes_the_complete_artifact_verifier(tmp_path: Path) -> None:
    """A real `uv build` of the current tree (metadata + content, not the isolated-venv smoke
    tests) passes every check: correct version, py.typed, and the a2a/mcp extras.

    This is the one test in this module that exercises the actual pinned Hatchling build backend
    and the project's real pyproject.toml, rather than a synthetic fixture.
    """
    repo_root = Path(__file__).resolve().parents[2]
    uv_executable = verify.UV_EXECUTABLE
    result = subprocess.run(  # noqa: S603
        [uv_executable, "build", "--out-dir", str(tmp_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr

    expected_version = verify.read_project_version(repo_root)
    wheel_path, sdist_path = verify.find_artifacts(tmp_path)

    assert expected_version == "0.4.2"
    assert wheel_path.name == f"{DIST_NAME}-0.4.2-py3-none-any.whl"
    assert verify.inspect_wheel(wheel_path, expected_version) == []
    assert verify.inspect_sdist(sdist_path, expected_version) == []
