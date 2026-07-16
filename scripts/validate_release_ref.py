#!/usr/bin/env python3
"""Validate that a requested release ref is safe to publish.

Rejects dirty, moving, malformed, or mismatched release refs before the release workflow reaches
its privileged publication step. Run after checking out the requested ref, from the repository
root, so ``pyproject.toml`` on disk reflects the ref's own tree.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path

TAG_REF_PATTERN = re.compile(r"^refs/tags/v(\d+\.\d+\.\d+)$")


def _resolve_git_executable() -> str:
    """Resolve the full path to the ``git`` executable, required for subprocess calls."""
    executable = shutil.which("git")
    if executable is None:
        raise SystemExit("git executable not found on PATH")
    return executable


GIT_EXECUTABLE: str = _resolve_git_executable()


def parse_tag_ref(ref: str) -> str | None:
    """Extract the ``X.Y.Z`` version from a ``refs/tags/vX.Y.Z`` ref, or ``None`` if malformed."""
    match = TAG_REF_PATTERN.fullmatch(ref)
    return match.group(1) if match else None


def read_project_version(pyproject_path: Path) -> str:
    """Read the package version from a pyproject.toml file."""
    with pyproject_path.open("rb") as handle:
        project = tomllib.load(handle)
    version = project["project"]["version"]
    if not isinstance(version, str):
        raise SystemExit(f"{pyproject_path}: [project.version] must be a string")
    return version


def check_annotated_tag(tag_name: str, repo_root: Path) -> bool:
    """Return True if ``tag_name`` is an annotated tag object, not a lightweight tag."""
    result = subprocess.run(  # noqa: S603
        [GIT_EXECUTABLE, "cat-file", "-t", tag_name],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "tag"


def check_clean_tree(repo_root: Path) -> bool:
    """Return True if the working tree has no uncommitted changes."""
    result = subprocess.run(  # noqa: S603
        [GIT_EXECUTABLE, "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == ""


def resolve_tag_commit(tag_name: str, repo_root: Path) -> str | None:
    """Peel a tag to the commit SHA it ultimately points at, or None if it does not resolve.

    Works for both annotated and lightweight tags: ``^{commit}`` dereferences an annotated tag
    object to its target commit and is a no-op for a lightweight tag, which already points
    directly at a commit.
    """
    result = subprocess.run(  # noqa: S603
        [GIT_EXECUTABLE, "rev-parse", f"{tag_name}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def resolve_head_commit(repo_root: Path) -> str | None:
    """Return the commit SHA that HEAD currently points at, or None if it cannot be resolved."""
    result = subprocess.run(  # noqa: S603
        [GIT_EXECUTABLE, "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def write_github_output(path: Path, values: Mapping[str, str]) -> None:
    """Append step outputs using the GitHub Actions GITHUB_OUTPUT environment-file format.

    Only single-line values are supported: a newline in a key or value could forge additional
    output lines, and neither a commit SHA nor a vX.Y.Z tag name should ever contain one.
    """
    lines: list[str] = []
    for key, value in values.items():
        if "\n" in key or "\n" in value:
            raise SystemExit(f"refusing to write a multiline GitHub Actions output: {key!r}")
        lines.append(f"{key}={value}\n")
    with path.open("a", encoding="utf-8") as handle:
        handle.writelines(lines)


def validate_release(
    *,
    ref: str,
    input_version: str,
    pyproject_version: str,
    is_annotated_tag: bool,
    is_clean_tree: bool,
    sha_matches_head: bool,
) -> list[str]:
    """Validate a release request against pure, already-gathered facts.

    Kept free of I/O so every rejection path is unit-testable without a real git repository.
    """
    errors: list[str] = []

    tag_version = parse_tag_ref(ref)
    if tag_version is None:
        errors.append(f"ref {ref!r} is not an annotated release tag of the form refs/tags/vX.Y.Z")
        return errors

    if tag_version != input_version:
        errors.append(
            f"requested version {input_version!r} does not match tag version {tag_version!r}"
        )
    if tag_version != pyproject_version:
        errors.append(
            f"tag version {tag_version!r} does not match pyproject.toml version "
            f"{pyproject_version!r} at the checked-out commit"
        )
    if not is_annotated_tag:
        errors.append(f"v{tag_version} is not an annotated tag; lightweight tags are rejected")
    if not is_clean_tree:
        errors.append("working tree is dirty at the checked-out ref")
    if not sha_matches_head:
        errors.append(
            f"checked-out HEAD does not match v{tag_version}'s peeled commit SHA; "
            "the tag may have moved or HEAD is not the tag's commit"
        )

    return errors


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref", required=True, help="the checked-out git ref, e.g. refs/tags/v0.3.1"
    )
    parser.add_argument(
        "--version",
        default=None,
        help="the requested release version, e.g. 0.3.1 (required unless --expect-commit is set)",
    )
    parser.add_argument(
        "--expect-commit",
        default=None,
        help=(
            "skip full validation; only re-verify that --ref's tag still resolves to this "
            "commit SHA (used by jobs downstream of validate to detect a moved tag)"
        ),
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        default=None,
        help="path to append commit_sha/tag outputs to on success, e.g. $GITHUB_OUTPUT",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def _verify_tag_unmoved(ref: str, expected_commit: str, repo_root: Path) -> int:
    """Re-check that the tag validated earlier still resolves to the same commit.

    Used by every job downstream of ``validate`` so none of them ever trusts a tag name on its
    own again; each re-derives its own proof against the SHA the validate job produced.
    """
    tag_version = parse_tag_ref(ref)
    if tag_version is None:
        print(f"ref {ref!r} is not a well-formed refs/tags/vX.Y.Z ref", file=sys.stderr)
        return 1
    resolved = resolve_tag_commit(f"v{tag_version}", repo_root)
    if resolved != expected_commit:
        print(
            f"tag v{tag_version} now resolves to {resolved!r}, expected {expected_commit!r} "
            "-- the tag moved after validation",
            file=sys.stderr,
        )
        return 1
    print(f"v{tag_version} still resolves to the validated commit {expected_commit}.")
    return 0


def main() -> int:
    """Validate the requested release ref and report the result."""
    args = parse_args()

    if args.expect_commit is not None:
        return _verify_tag_unmoved(args.ref, args.expect_commit, args.repo_root)

    if args.version is None:
        print("--version is required unless --expect-commit is set", file=sys.stderr)
        return 2

    pyproject_version = read_project_version(args.repo_root / "pyproject.toml")

    tag_version = parse_tag_ref(args.ref)
    resolved_commit_sha = (
        resolve_tag_commit(f"v{tag_version}", args.repo_root) if tag_version is not None else None
    )
    head_commit_sha = resolve_head_commit(args.repo_root)
    sha_matches_head = (
        resolved_commit_sha is not None
        and head_commit_sha is not None
        and resolved_commit_sha == head_commit_sha
    )
    is_annotated_tag = tag_version is not None and check_annotated_tag(
        f"v{tag_version}", args.repo_root
    )
    is_clean_tree = check_clean_tree(args.repo_root)

    errors = validate_release(
        ref=args.ref,
        input_version=args.version,
        pyproject_version=pyproject_version,
        is_annotated_tag=is_annotated_tag,
        is_clean_tree=is_clean_tree,
        sha_matches_head=sha_matches_head,
    )
    if errors:
        print("Release ref validation failed:", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        return 1

    if tag_version is None or resolved_commit_sha is None:
        print("internal error: validation passed without a resolved tag/commit", file=sys.stderr)
        return 1

    print(f"Release ref validation passed: v{tag_version} matches version {pyproject_version}.")
    print(f"Validated commit: {resolved_commit_sha}")

    if args.github_output is not None:
        write_github_output(
            args.github_output, {"commit_sha": resolved_commit_sha, "tag": f"v{tag_version}"}
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
