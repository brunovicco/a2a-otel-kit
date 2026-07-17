"""Regression tests for release readiness and immutable historical tags.

These guard the specific corrections made after the first packaging pass: v0.3.0 must never be
selected for publication, the release tree must actually contain the release tooling it
documents, and the build backend must be exactly pinned.
"""

import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GIT_EXECUTABLE = shutil.which("git")


def _load_pyproject() -> dict[str, Any]:
    """Parse the repository's own pyproject.toml."""
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_project_version_is_0_4_1() -> None:
    """The package version matches the documentation correction release."""
    project = _load_pyproject()

    assert project["project"]["version"] == "0.4.1"


def test_readme_integration_commands_select_integration_tests() -> None:
    """README commands must override pytest's project-wide unit-only marker."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert readme.count("--no-cov -m integration") == 2


@pytest.mark.parametrize("relative_path", ["README.md", ".env.example", "examples/README.md"])
def test_documented_collector_endpoints_target_otlp_traces(relative_path: str) -> None:
    """Every local Collector example must use the exporter's concrete traces endpoint."""
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    for line in text.splitlines():
        if "4318" in line and "otlp_endpoint" in line.lower():
            assert "/v1/traces" in line, f"{relative_path} has incomplete OTLP endpoint: {line}"


def test_build_system_pins_hatchling_to_an_exact_version() -> None:
    """The build backend is an exact pin (==), not a range, so the isolated build env is fixed."""
    project = _load_pyproject()

    requires = project["build-system"]["requires"]

    assert len(requires) == 1
    assert re.fullmatch(r"hatchling==\d+\.\d+\.\d+", requires[0]), requires[0]


@pytest.mark.parametrize(
    "relative_path",
    [
        ".github/workflows/release.yml",
        "scripts/validate_release_ref.py",
        "scripts/verify_release_artifacts.py",
        "LICENSE",
        "CHANGELOG.md",
    ],
)
def test_release_tooling_exists_in_the_working_tree(relative_path: str) -> None:
    """The files a v0.3.1 tag will ship are actually present in the tree about to be tagged."""
    assert (REPO_ROOT / relative_path).is_file(), relative_path


def test_changelog_explicitly_states_v030_must_not_be_published() -> None:
    """The changelog carries an unambiguous, greppable statement of the v0.3.0 restriction."""
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "must never be published to PyPI" in changelog
    assert "v0.3.0" in changelog


@pytest.mark.parametrize(
    "doc_path",
    ["README.md", "CHANGELOG.md", "docs/DEVELOPMENT.md"],
)
def test_documentation_never_instructs_moving_or_recreating_v030(doc_path: str) -> None:
    """No doc tells a maintainer to force-move, delete, or recreate the v0.3.0 tag."""
    text = (REPO_ROOT / doc_path).read_text(encoding="utf-8")

    dangerous_patterns = (
        "tag -f v0.3.0",
        "tag -d v0.3.0",
        "tag --force v0.3.0",
        "push --force",
        "push -f origin v0.3.0",
    )
    for pattern in dangerous_patterns:
        assert pattern not in text, f"{doc_path} contains {pattern!r}"


def _tag_commit_is_fetched(tag: str) -> bool:
    """Return True if the tag's commit is present locally (false on a shallow, tag-less clone)."""
    if GIT_EXECUTABLE is None:
        return False
    result = subprocess.run(  # noqa: S603
        [GIT_EXECUTABLE, "rev-parse", "--verify", f"{tag}^{{commit}}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _show_tag_file(tag: str, relative_path: str) -> subprocess.CompletedProcess[str]:
    """Run git show for one file at one tag."""
    assert GIT_EXECUTABLE is not None
    return subprocess.run(  # noqa: S603
        [GIT_EXECUTABLE, "cat-file", "-e", f"{tag}:{relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(
    not _tag_commit_is_fetched("v0.3.0"),
    reason="v0.3.0 tag not available in this checkout (e.g. a shallow CI clone)",
)
@pytest.mark.parametrize(
    "relative_path",
    [
        ".github/workflows/release.yml",
        "scripts/validate_release_ref.py",
        "scripts/verify_release_artifacts.py",
        "LICENSE",
    ],
)
def test_v030_tag_tree_lacks_the_release_tooling_it_would_need(relative_path: str) -> None:
    """The real, immutable v0.3.0 tag has none of this milestone's release tooling.

    This is the concrete reason v0.3.0 can never be published through release.yml: the tree that
    tag points at cannot produce a compliant package, and the tag must never be moved to fix that.
    """
    result = _show_tag_file("v0.3.0", relative_path)

    assert result.returncode != 0, f"v0.3.0 unexpectedly already contains {relative_path}"
