"""Tests for scripts/validate_release_ref.py."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "validate_release_ref.py"


def _load_module(name: str, relative_path: str) -> ModuleType:
    """Load a scripts/*.py module by file path; scripts/ is not an importable package."""
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate = _load_module("validate_release_ref", "scripts/validate_release_ref.py")


def test_parse_tag_ref_extracts_the_version_from_a_well_formed_tag() -> None:
    """A vX.Y.Z tag ref yields its X.Y.Z version."""
    assert validate.parse_tag_ref("refs/tags/v0.3.1") == "0.3.1"


@pytest.mark.parametrize(
    "ref",
    [
        "refs/heads/main",
        "refs/tags/0.3.1",
        "refs/tags/v0.3",
        "refs/tags/v0.3.1-rc1",
        "refs/tags/release-0.3.1",
        "v0.3.1",
        "",
    ],
)
def test_parse_tag_ref_rejects_malformed_refs(ref: str) -> None:
    """Anything other than an exact refs/tags/vX.Y.Z ref is rejected."""
    assert validate.parse_tag_ref(ref) is None


def test_validate_release_passes_for_a_matching_annotated_clean_bound_tag() -> None:
    """A well-formed tag with matching versions, annotated, clean, SHA-bound, passes."""
    errors = validate.validate_release(
        ref="refs/tags/v0.3.1",
        input_version="0.3.1",
        pyproject_version="0.3.1",
        is_annotated_tag=True,
        is_clean_tree=True,
        sha_matches_head=True,
    )

    assert errors == []


def test_validate_release_rejects_a_malformed_ref() -> None:
    """A ref that is not refs/tags/vX.Y.Z is rejected before any other check runs."""
    errors = validate.validate_release(
        ref="refs/heads/main",
        input_version="0.3.1",
        pyproject_version="0.3.1",
        is_annotated_tag=True,
        is_clean_tree=True,
        sha_matches_head=True,
    )

    assert len(errors) == 1
    assert "not an annotated release tag" in errors[0]


def test_validate_release_rejects_a_tag_input_version_mismatch() -> None:
    """The workflow_dispatch version input must match the tag's own version."""
    errors = validate.validate_release(
        ref="refs/tags/v0.3.1",
        input_version="0.3.2",
        pyproject_version="0.3.1",
        is_annotated_tag=True,
        is_clean_tree=True,
        sha_matches_head=True,
    )

    assert any("does not match tag version" in error for error in errors)


def test_validate_release_rejects_a_tag_pyproject_version_mismatch() -> None:
    """The tag's version must match pyproject.toml at the checked-out commit."""
    errors = validate.validate_release(
        ref="refs/tags/v0.3.1",
        input_version="0.3.1",
        pyproject_version="0.3.0",
        is_annotated_tag=True,
        is_clean_tree=True,
        sha_matches_head=True,
    )

    assert any("does not match pyproject.toml version" in error for error in errors)


def test_validate_release_rejects_a_lightweight_tag() -> None:
    """A lightweight (non-annotated) tag is rejected even when versions match."""
    errors = validate.validate_release(
        ref="refs/tags/v0.3.1",
        input_version="0.3.1",
        pyproject_version="0.3.1",
        is_annotated_tag=False,
        is_clean_tree=True,
        sha_matches_head=True,
    )

    assert any("not an annotated tag" in error for error in errors)


def test_validate_release_rejects_a_dirty_tree() -> None:
    """A dirty working tree at the checked-out ref is rejected."""
    errors = validate.validate_release(
        ref="refs/tags/v0.3.1",
        input_version="0.3.1",
        pyproject_version="0.3.1",
        is_annotated_tag=True,
        is_clean_tree=False,
        sha_matches_head=True,
    )

    assert any("dirty" in error for error in errors)


def test_validate_release_rejects_a_sha_mismatch() -> None:
    """A checked-out HEAD that does not match the tag's peeled commit is rejected.

    This is the immutable-SHA-binding guarantee: even a well-formed, annotated, clean, matching
    tag must be rejected if the tree actually checked out is not the tag's own commit.
    """
    errors = validate.validate_release(
        ref="refs/tags/v0.3.1",
        input_version="0.3.1",
        pyproject_version="0.3.1",
        is_annotated_tag=True,
        is_clean_tree=True,
        sha_matches_head=False,
    )

    assert any("does not match" in error and "peeled commit SHA" in error for error in errors)


def _run_git(repo: Path, *args: str) -> None:
    """Run a git command against a test fixture repository."""
    subprocess.run(  # noqa: S603
        [validate.GIT_EXECUTABLE, *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _git_output(repo: Path, *args: str) -> str:
    """Run a git command and return its trimmed stdout."""
    result = subprocess.run(  # noqa: S603
        [validate.GIT_EXECUTABLE, *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A minimal local git repository with one commit, used to test the git-invoking helpers."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "--initial-branch=main")
    _run_git(repo, "config", "user.email", "test@example.invalid")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "pyproject.toml").write_text('[project]\nversion = "0.3.1"\n')
    _run_git(repo, "add", "pyproject.toml")
    _run_git(repo, "commit", "-m", "initial commit")
    return repo


def test_check_annotated_tag_is_true_for_an_annotated_tag(git_repo: Path) -> None:
    """git cat-file reports an annotated tag as a 'tag' object."""
    _run_git(git_repo, "tag", "-a", "v0.3.1", "-m", "Release 0.3.1")

    assert validate.check_annotated_tag("v0.3.1", git_repo) is True


def test_check_annotated_tag_is_false_for_a_lightweight_tag(git_repo: Path) -> None:
    """git cat-file reports a lightweight tag as a 'commit' object, not a 'tag'."""
    _run_git(git_repo, "tag", "v0.3.1")

    assert validate.check_annotated_tag("v0.3.1", git_repo) is False


def test_check_clean_tree_is_true_with_no_local_changes(git_repo: Path) -> None:
    """A freshly checked-out tree with no modifications is clean."""
    assert validate.check_clean_tree(git_repo) is True


def test_check_clean_tree_is_false_with_an_uncommitted_change(git_repo: Path) -> None:
    """A modified tracked file makes the tree dirty."""
    (git_repo / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')

    assert validate.check_clean_tree(git_repo) is False


def test_read_project_version_reads_the_declared_version(git_repo: Path) -> None:
    """The version is read from [project.version] in pyproject.toml."""
    assert validate.read_project_version(git_repo / "pyproject.toml") == "0.3.1"


def test_resolve_tag_commit_peels_an_annotated_tag_to_its_commit(git_repo: Path) -> None:
    """An annotated tag's own object SHA differs from the commit it ultimately points at."""
    _run_git(git_repo, "tag", "-a", "v0.3.1", "-m", "Release 0.3.1")
    commit_sha = _git_output(git_repo, "rev-parse", "HEAD")

    assert validate.resolve_tag_commit("v0.3.1", git_repo) == commit_sha


def test_resolve_tag_commit_resolves_a_lightweight_tag_to_its_commit(git_repo: Path) -> None:
    """Peeling a lightweight tag is a no-op: it already points directly at a commit."""
    _run_git(git_repo, "tag", "v0.3.1")
    commit_sha = _git_output(git_repo, "rev-parse", "HEAD")

    assert validate.resolve_tag_commit("v0.3.1", git_repo) == commit_sha


def test_resolve_tag_commit_returns_none_for_an_unknown_tag(git_repo: Path) -> None:
    """A tag that does not exist resolves to None rather than raising."""
    assert validate.resolve_tag_commit("v9.9.9", git_repo) is None


def test_resolve_head_commit_matches_git_rev_parse_head(git_repo: Path) -> None:
    """resolve_head_commit agrees with a direct git rev-parse HEAD."""
    assert validate.resolve_head_commit(git_repo) == _git_output(git_repo, "rev-parse", "HEAD")


def test_resolve_tag_commit_detects_a_tag_moved_to_a_new_commit(git_repo: Path) -> None:
    """Re-pointing a tag changes what it peels to -- the TOCTOU scenario this guards against."""
    _run_git(git_repo, "tag", "-a", "v0.3.1", "-m", "Release 0.3.1")
    original_commit = validate.resolve_tag_commit("v0.3.1", git_repo)

    (git_repo / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')
    _run_git(git_repo, "add", "pyproject.toml")
    _run_git(git_repo, "commit", "-m", "a later, unrelated commit")
    _run_git(git_repo, "tag", "-f", "-a", "v0.3.1", "-m", "Release 0.3.1 (moved)")

    moved_commit = validate.resolve_tag_commit("v0.3.1", git_repo)

    assert moved_commit != original_commit


def test_write_github_output_appends_key_value_lines(tmp_path: Path) -> None:
    """Outputs are appended in the GITHUB_OUTPUT environment-file format."""
    output_file = tmp_path / "github_output"
    output_file.write_text("")

    validate.write_github_output(output_file, {"commit_sha": "abc123", "tag": "v0.3.1"})

    assert output_file.read_text() == "commit_sha=abc123\ntag=v0.3.1\n"


def test_write_github_output_rejects_a_multiline_value(tmp_path: Path) -> None:
    """A newline in a value could forge extra output lines and is refused outright."""
    output_file = tmp_path / "github_output"
    output_file.write_text("")

    with pytest.raises(SystemExit):
        validate.write_github_output(output_file, {"tag": "v0.3.1\nmalicious=true"})


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the script as a subprocess, exactly as the release workflow does."""
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_full_validation_writes_commit_sha_and_tag_outputs(
    git_repo: Path, tmp_path: Path
) -> None:
    """A full, successful validation run writes both outputs GitHub Actions jobs consume."""
    _run_git(git_repo, "tag", "-a", "v0.3.1", "-m", "Release 0.3.1")
    commit_sha = _git_output(git_repo, "rev-parse", "HEAD")
    output_file = tmp_path / "github_output"
    output_file.write_text("")

    result = _run_cli(
        "--ref",
        "refs/tags/v0.3.1",
        "--version",
        "0.3.1",
        "--repo-root",
        str(git_repo),
        "--github-output",
        str(output_file),
    )

    assert result.returncode == 0, result.stderr
    assert output_file.read_text() == f"commit_sha={commit_sha}\ntag=v0.3.1\n"


def test_cli_expect_commit_mode_passes_when_tag_still_matches(git_repo: Path) -> None:
    """The narrow re-check mode used by later jobs passes when the tag has not moved."""
    _run_git(git_repo, "tag", "-a", "v0.3.1", "-m", "Release 0.3.1")
    commit_sha = _git_output(git_repo, "rev-parse", "HEAD")

    result = _run_cli(
        "--ref",
        "refs/tags/v0.3.1",
        "--expect-commit",
        commit_sha,
        "--repo-root",
        str(git_repo),
    )

    assert result.returncode == 0, result.stderr


def test_cli_expect_commit_mode_fails_when_the_tag_moved(git_repo: Path) -> None:
    """The narrow re-check mode fails closed when the tag now points somewhere else.

    This is the end-to-end behavioral proof of the anti-TOCTOU guarantee: a job that trusted an
    earlier validation must refuse to proceed once the tag it is re-checking has been re-pointed.
    """
    _run_git(git_repo, "tag", "-a", "v0.3.1", "-m", "Release 0.3.1")
    original_commit = _git_output(git_repo, "rev-parse", "HEAD")

    (git_repo / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')
    _run_git(git_repo, "add", "pyproject.toml")
    _run_git(git_repo, "commit", "-m", "a later, unrelated commit")
    _run_git(git_repo, "tag", "-f", "-a", "v0.3.1", "-m", "Release 0.3.1 (moved)")

    result = _run_cli(
        "--ref",
        "refs/tags/v0.3.1",
        "--expect-commit",
        original_commit,
        "--repo-root",
        str(git_repo),
    )

    assert result.returncode == 1
    assert "the tag moved after validation" in result.stderr


def test_cli_requires_version_unless_expect_commit_is_set(git_repo: Path) -> None:
    """Omitting both --version and --expect-commit is a usage error, not a silent pass."""
    result = _run_cli("--ref", "refs/tags/v0.3.1", "--repo-root", str(git_repo))

    assert result.returncode == 2
    assert "--version is required" in result.stderr
