#!/usr/bin/env python3
"""Verify a built wheel and sdist before they are trusted for release.

Inspects the artifacts already produced by ``uv build`` (this script never builds anything
itself, so it always verifies the exact bytes a caller intends to publish), then installs the
wheel into isolated temporary virtual environments and smoke-tests imports with a network-I/O
guard, so a network call during import would fail the run rather than silently succeed.
"""

import argparse
import email
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from email.message import Message
from pathlib import Path


def _resolve_uv_executable() -> str:
    """Resolve the full path to the ``uv`` executable, required for subprocess calls."""
    executable = shutil.which("uv")
    if executable is None:
        raise SystemExit("uv executable not found on PATH")
    return executable


UV_EXECUTABLE: str = _resolve_uv_executable()

DISTRIBUTION_NAME = "a2a-otel-kit"
PACKAGE_NAME = "a2a_otel_kit"
REQUIRED_MODULES = (
    "__init__.py",
    "py.typed",
    "domain/__init__.py",
    "domain/attributes.py",
    "domain/errors.py",
    "application/__init__.py",
    "application/ports.py",
    "application/settings.py",
    "adapters/__init__.py",
    "adapters/propagation.py",
    "adapters/tracing.py",
    "adapters/a2a.py",
    "adapters/mcp.py",
    "entrypoints/__init__.py",
    "entrypoints/logging.py",
    "entrypoints/observability.py",
)
REQUIRED_SDIST_FILES = ("README.md", "LICENSE", "pyproject.toml")
EXPECTED_EXTRAS = ("a2a", "mcp")
NETWORK_GUARD_SNIPPET = (
    "import socket\n"
    "def _blocked(*_a, **_k):\n"
    "    raise AssertionError('network I/O attempted during smoke test')\n"
    "socket.socket.connect = _blocked\n"
    "socket.socket.connect_ex = _blocked\n"
)


def find_artifacts(dist_dir: Path) -> tuple[Path, Path]:
    """Locate exactly one wheel and one sdist in the given directory."""
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1:
        raise SystemExit(f"expected exactly one wheel in {dist_dir}, found {len(wheels)}")
    if len(sdists) != 1:
        raise SystemExit(f"expected exactly one sdist in {dist_dir}, found {len(sdists)}")
    return wheels[0], sdists[0]


def parse_metadata(raw: bytes) -> Message:
    """Parse an RFC822-style METADATA/PKG-INFO payload."""
    return email.message_from_bytes(raw)


def check_common_metadata(metadata: Message, expected_version: str, source: str) -> list[str]:
    """Validate the fields shared by wheel METADATA and sdist PKG-INFO."""
    errors: list[str] = []
    if metadata.get("Name") != DISTRIBUTION_NAME:
        errors.append(f"{source}: Name is {metadata.get('Name')!r}, expected {DISTRIBUTION_NAME!r}")
    if metadata.get("Version") != expected_version:
        errors.append(
            f"{source}: Version is {metadata.get('Version')!r}, expected {expected_version!r}"
        )
    if metadata.get("License-Expression") != "MIT":
        errors.append(f"{source}: License-Expression is {metadata.get('License-Expression')!r}")
    if not metadata.get("Requires-Python"):
        errors.append(f"{source}: missing Requires-Python")
    extras = set(metadata.get_all("Provides-Extra") or [])
    missing_extras = set(EXPECTED_EXTRAS) - extras
    if missing_extras:
        errors.append(f"{source}: missing Provides-Extra entries {sorted(missing_extras)}")
    return errors


def inspect_wheel(wheel_path: Path, expected_version: str) -> list[str]:
    """Inspect wheel contents and metadata.

    The dist-info directory name is discovered from the archive itself, never built from
    ``expected_version``: a wheel whose actual version differs from what is expected must still be
    inspectable, so the mismatch is reported as a version error rather than a "file not found".
    """
    errors: list[str] = []
    with zipfile.ZipFile(wheel_path) as archive:
        names = set(archive.namelist())
        for module in REQUIRED_MODULES:
            entry = f"{PACKAGE_NAME}/{module}"
            if entry not in names:
                errors.append(f"wheel: missing {entry}")
        metadata_entries = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_entries) != 1:
            errors.append(f"wheel: expected exactly one *.dist-info/METADATA, found {names}")
            return errors
        metadata = parse_metadata(archive.read(metadata_entries[0]))
        errors.extend(check_common_metadata(metadata, expected_version, "wheel"))
        payload = metadata.get_payload()
        if not isinstance(payload, str) or not payload.strip():
            errors.append("wheel: METADATA has an empty long description")
    return errors


def inspect_sdist(sdist_path: Path, expected_version: str) -> list[str]:
    """Inspect sdist contents and metadata.

    The top-level directory prefix is discovered from the archive itself, never built from
    ``expected_version``, for the same reason as :func:`inspect_wheel`.
    """
    errors: list[str] = []
    with tarfile.open(sdist_path, "r:gz") as archive:
        names = set(archive.getnames())
        top_level_dirs = {name.split("/", 1)[0] for name in names if "/" in name}
        if len(top_level_dirs) != 1:
            errors.append(f"sdist: expected exactly one top-level directory, found {names}")
            return errors
        prefix = next(iter(top_level_dirs))
        for required in REQUIRED_SDIST_FILES:
            entry = f"{prefix}/{required}"
            if entry not in names:
                errors.append(f"sdist: missing {entry}")
        for module in REQUIRED_MODULES:
            entry = f"{prefix}/src/{PACKAGE_NAME}/{module}"
            if entry not in names:
                errors.append(f"sdist: missing {entry}")
        pkg_info_entry = f"{prefix}/PKG-INFO"
        if pkg_info_entry not in names:
            errors.append(f"sdist: missing {pkg_info_entry}")
            return errors
        member = archive.extractfile(pkg_info_entry)
        if member is None:
            errors.append(f"sdist: {pkg_info_entry} is not a regular file")
            return errors
        metadata = parse_metadata(member.read())
        errors.extend(check_common_metadata(metadata, expected_version, "sdist"))
    return errors


def hash_and_size(path: Path) -> tuple[str, int]:
    """Compute the SHA-256 hex digest and size in bytes of a file."""
    digest = hashlib.sha256(path.read_bytes())
    return digest.hexdigest(), path.stat().st_size


def print_artifact_summary(wheel_path: Path, sdist_path: Path) -> None:
    """Print filenames, sizes, and SHA-256 hashes for both artifacts."""
    for path in (wheel_path, sdist_path):
        digest, size = hash_and_size(path)
        print(f"{path.name}: {size} bytes, sha256={digest}")


def smoke_test_import(venv_python: Path, import_statement: str) -> str | None:
    """Run one import statement in an isolated interpreter with network blocked.

    Returns an error message on failure, or ``None`` on success.
    """
    script = f"{NETWORK_GUARD_SNIPPET}\n{import_statement}\n"
    result = subprocess.run(  # noqa: S603
        [str(venv_python), "-I", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        return f"smoke test failed for {import_statement!r}: {result.stderr.strip()}"
    return None


def run_smoke_tests(wheel_path: Path) -> list[str]:
    """Install the wheel into isolated venvs and smoke-test base/a2a/mcp imports offline."""
    errors: list[str] = []
    scenarios: tuple[tuple[str, str, str], ...] = (
        ("base", "", "import a2a_otel_kit"),
        ("a2a", "[a2a]", "import a2a_otel_kit.adapters.a2a"),
        ("mcp", "[mcp]", "import a2a_otel_kit.adapters.mcp"),
    )
    for label, extra, import_statement in scenarios:
        with tempfile.TemporaryDirectory(prefix=f"a2a-otel-kit-verify-{label}-") as tmp:
            venv_dir = Path(tmp) / "venv"
            create = subprocess.run(  # noqa: S603
                [UV_EXECUTABLE, "venv", str(venv_dir), "--python", "3.13"],
                capture_output=True,
                text=True,
                check=False,
            )
            if create.returncode != 0:
                errors.append(f"{label}: failed to create venv: {create.stderr.strip()}")
                continue
            venv_python = venv_dir / "bin" / "python"
            install = subprocess.run(  # noqa: S603
                [
                    UV_EXECUTABLE,
                    "pip",
                    "install",
                    "--python",
                    str(venv_python),
                    f"{wheel_path}{extra}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if install.returncode != 0:
                errors.append(f"{label}: failed to install wheel: {install.stderr.strip()}")
                continue
            failure = smoke_test_import(venv_python, import_statement)
            if failure is not None:
                errors.append(f"{label}: {failure}")
    return errors


def read_project_version(root: Path) -> str:
    """Read the package version from the local pyproject.toml."""

    with (root / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)
    version = project["project"]["version"]
    if not isinstance(version, str):
        raise SystemExit("pyproject.toml: [project.version] must be a string")
    return version


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist-dir", type=Path, default=Path("dist"), help="directory containing built artifacts"
    )
    parser.add_argument(
        "--version",
        default=None,
        help="expected package version (default: read from pyproject.toml)",
    )
    parser.add_argument(
        "--skip-smoke-test",
        action="store_true",
        help="skip installing the wheel into isolated venvs (metadata/content checks only)",
    )
    return parser.parse_args()


def main() -> int:
    """Verify the built artifacts and report the result."""
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    expected_version = args.version or read_project_version(root)

    wheel_path, sdist_path = find_artifacts(args.dist_dir)
    print_artifact_summary(wheel_path, sdist_path)

    errors = [
        *inspect_wheel(wheel_path, expected_version),
        *inspect_sdist(sdist_path, expected_version),
    ]
    if not args.skip_smoke_test:
        errors.extend(run_smoke_tests(wheel_path))

    if errors:
        print("\nArtifact verification failed:", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        return 1

    print("\nArtifact verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
