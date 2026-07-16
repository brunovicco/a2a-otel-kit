"""Structural and least-privilege checks for the GitHub Actions workflows.

PyYAML parses the unquoted ``on:`` key as the boolean ``True`` (a YAML 1.1 quirk); GitHub's own
parser treats it as the literal trigger key. ``_triggers()`` below compensates for that so these
tests read the same triggers GitHub Actions does.
"""

from pathlib import Path
from typing import Any

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"
RELEASE_WORKFLOW = WORKFLOWS_DIR / "release.yml"
QUALITY_WORKFLOW = WORKFLOWS_DIR / "quality.yml"


def _load(path: Path) -> dict[Any, Any]:
    """Parse a workflow file. Keys are ``Any`` because PyYAML parses bare ``on:`` as ``True``."""
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    assert isinstance(document, dict)
    return document


def _triggers(document: dict[Any, Any]) -> dict[str, Any]:
    """Return the workflow's trigger mapping, working around the on:/True PyYAML quirk."""
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _permissions(job: dict[str, Any], document: dict[str, Any]) -> dict[str, str]:
    """Return a job's effective permissions, falling back to the workflow-level default."""
    permissions = job.get("permissions", document.get("permissions"))
    assert isinstance(permissions, dict)
    return permissions


def _all_run_and_with_text(document: dict[str, Any]) -> str:
    """Concatenate every run:/with: string in the workflow, for text-level secret scanning."""
    chunks: list[str] = []
    for job in document["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run")
            if isinstance(run, str):
                chunks.append(run)
            with_block = step.get("with", {})
            if isinstance(with_block, dict):
                chunks.extend(str(value) for value in with_block.values())
    return "\n".join(chunks)


def test_release_workflow_triggers_only_on_workflow_dispatch() -> None:
    """No push/pull_request trigger can reach the privileged publication job."""
    document = _load(RELEASE_WORKFLOW)

    triggers = _triggers(document)

    assert set(triggers) == {"workflow_dispatch"}


def test_release_workflow_requires_ref_and_version_inputs() -> None:
    """A manual run must supply both the tag ref and the version to publish."""
    document = _load(RELEASE_WORKFLOW)

    inputs = _triggers(document)["workflow_dispatch"]["inputs"]

    assert inputs["ref"]["required"] is True
    assert inputs["version"]["required"] is True


def test_release_workflow_has_a_concurrency_group() -> None:
    """Two releases of the same ref cannot run at once."""
    document = _load(RELEASE_WORKFLOW)

    concurrency = document["concurrency"]

    assert "${{ inputs.ref }}" in concurrency["group"]
    assert concurrency["cancel-in-progress"] is False


def test_release_workflow_default_permissions_are_read_only() -> None:
    """The workflow-level default grants nothing beyond read access to repository contents."""
    document = _load(RELEASE_WORKFLOW)

    assert document["permissions"] == {"contents": "read"}


def test_release_workflow_validate_and_build_jobs_stay_read_only() -> None:
    """The two unprivileged jobs never gain id-token or contents:write."""
    document = _load(RELEASE_WORKFLOW)

    for job_name in ("validate", "build"):
        permissions = _permissions(document["jobs"][job_name], document)
        assert permissions.get("id-token") != "write"
        assert permissions.get("contents") != "write"


def test_release_workflow_publish_job_has_only_id_token_write() -> None:
    """id-token: write is granted only to the job that talks to PyPI, and nothing is writable."""
    document = _load(RELEASE_WORKFLOW)

    permissions = _permissions(document["jobs"]["publish"], document)

    assert permissions["id-token"] == "write"
    assert permissions.get("contents") != "write"


def test_release_workflow_publish_job_runs_only_for_workflow_dispatch() -> None:
    """The privileged publish job explicitly refuses to run for any other event."""
    document = _load(RELEASE_WORKFLOW)

    publish_job = document["jobs"]["publish"]

    assert publish_job["if"] == "github.event_name == 'workflow_dispatch'"


def test_release_workflow_publish_job_depends_on_the_verified_build() -> None:
    """Publication receives validation outputs and runs only after the verified build succeeds."""
    document = _load(RELEASE_WORKFLOW)

    assert document["jobs"]["publish"]["needs"] == ["validate", "build"]


def test_publish_job_checks_out_the_validated_sha_not_the_raw_ref() -> None:
    """The privileged publish job checks out the immutable SHA produced by validation."""
    document = _load(RELEASE_WORKFLOW)

    publish_job = document["jobs"]["publish"]
    checkout = _find_step(publish_job["steps"], name_contains="Check out")

    assert checkout["with"]["ref"] == "${{ needs.validate.outputs.commit_sha }}"
    assert checkout["with"]["fetch-depth"] == 0
    assert publish_job["env"] == {
        "VALIDATED_SHA": "${{ needs.validate.outputs.commit_sha }}",
        "VALIDATED_TAG": "${{ needs.validate.outputs.tag }}",
    }


def test_publish_job_re_verifies_tag_binding_immediately_before_upload() -> None:
    """The privileged job rejects a moved tag directly before the irreversible PyPI upload."""
    document = _load(RELEASE_WORKFLOW)

    steps = _steps_by_job(document)["publish"]
    verify_step = _find_step(steps, name_contains="Re-verify")
    publish_step = next(
        step for step in steps if "pypa/gh-action-pypi-publish" in step.get("uses", "")
    )

    assert "validate_release_ref.py" in verify_step["run"]
    assert '--ref "refs/tags/$VALIDATED_TAG"' in verify_step["run"]
    assert '--expect-commit "$VALIDATED_SHA"' in verify_step["run"]
    assert steps.index(verify_step) + 1 == steps.index(publish_step)


def test_publish_job_never_uses_the_raw_release_ref() -> None:
    """No publish-job checkout or command resolves the unvalidated workflow input again."""
    document = _load(RELEASE_WORKFLOW)

    publish_job_text = yaml.safe_dump(document["jobs"]["publish"])

    assert "inputs.ref" not in publish_job_text


def test_release_workflow_github_release_job_runs_only_after_publish() -> None:
    """The GitHub Release is created only after a successful PyPI publish."""
    document = _load(RELEASE_WORKFLOW)

    needs = document["jobs"]["github-release"]["needs"]

    assert "publish" in needs


def test_release_workflow_github_release_job_has_contents_write() -> None:
    """Only the release-creation job can write repository contents (the Release itself)."""
    document = _load(RELEASE_WORKFLOW)

    permissions = _permissions(document["jobs"]["github-release"], document)

    assert permissions["contents"] == "write"


def test_release_workflow_publish_step_uses_trusted_publishing_not_a_token() -> None:
    """The PyPI publish step never sets a password/token input."""
    document = _load(RELEASE_WORKFLOW)

    publish_steps = document["jobs"]["publish"]["steps"]
    pypi_step = next(
        step for step in publish_steps if "pypa/gh-action-pypi-publish" in step.get("uses", "")
    )

    assert "password" not in pypi_step.get("with", {})
    assert "skip-existing" not in pypi_step.get("with", {})


def test_release_workflow_does_not_reference_a_pypi_token_secret() -> None:
    """No step reads a PyPI API token from repository secrets."""
    document = _load(RELEASE_WORKFLOW)

    text = _all_run_and_with_text(document)

    assert "secrets.PYPI" not in text
    assert "PYPI_TOKEN" not in text
    assert "PYPI_API_TOKEN" not in text


def test_release_workflow_actions_are_pinned_to_a_commit_sha() -> None:
    """Every third-party action is pinned by full commit SHA, not a mutable tag."""
    document = _load(RELEASE_WORKFLOW)

    for job in document["jobs"].values():
        for step in job.get("steps", []):
            uses = step.get("uses")
            if uses is None:
                continue
            ref = uses.split("@", 1)[1]
            assert len(ref) == 40, f"{uses!r} is not pinned to a full commit SHA"


def _steps_by_job(document: dict[Any, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return each job's step list, keyed by job name."""
    return {name: job.get("steps", []) for name, job in document["jobs"].items()}


def _find_step(steps: list[dict[str, Any]], *, name_contains: str) -> dict[str, Any]:
    """Return the first step whose name contains the given text."""
    return next(step for step in steps if name_contains in step.get("name", ""))


def test_validate_job_exposes_commit_sha_and_tag_outputs() -> None:
    """The validate job's outputs are wired to the validation step's own outputs."""
    document = _load(RELEASE_WORKFLOW)

    outputs = document["jobs"]["validate"]["outputs"]

    assert outputs["commit_sha"] == "${{ steps.validate.outputs.commit_sha }}"
    assert outputs["tag"] == "${{ steps.validate.outputs.tag }}"
    assert document["jobs"]["validate"]["steps"][-1]["id"] == "validate"


def test_build_job_checks_out_the_validated_sha_not_the_raw_ref() -> None:
    """The build job's checkout uses needs.validate.outputs.commit_sha, never inputs.ref."""
    document = _load(RELEASE_WORKFLOW)

    checkout = _find_step(_steps_by_job(document)["build"], name_contains="Check out")

    assert checkout["with"]["ref"] == "${{ needs.validate.outputs.commit_sha }}"


def test_github_release_job_checks_out_the_validated_sha_not_the_raw_ref() -> None:
    """The github-release job's checkout also uses the validated SHA, never inputs.ref."""
    document = _load(RELEASE_WORKFLOW)

    checkout = _find_step(_steps_by_job(document)["github-release"], name_contains="Check out")

    assert checkout["with"]["ref"] == "${{ needs.validate.outputs.commit_sha }}"


def test_build_job_re_verifies_the_tag_before_privileged_work() -> None:
    """The build job re-checks tag-to-SHA consistency using --expect-commit before building."""
    document = _load(RELEASE_WORKFLOW)

    step = _find_step(_steps_by_job(document)["build"], name_contains="Re-verify")

    assert "validate_release_ref.py" in step["run"]
    assert "--expect-commit" in step["run"]


def test_github_release_job_re_verifies_the_tag_before_creating_the_release() -> None:
    """The github-release job re-checks tag-to-SHA consistency before gh release create runs."""
    document = _load(RELEASE_WORKFLOW)

    steps = _steps_by_job(document)["github-release"]
    verify_step = _find_step(steps, name_contains="Re-verify")
    release_step = _find_step(steps, name_contains="Create GitHub Release")

    assert "--expect-commit" in verify_step["run"]
    assert steps.index(verify_step) < steps.index(release_step)


def test_github_release_step_uses_the_validated_short_tag() -> None:
    """gh release create receives the validated short tag (e.g. v0.3.1), not a raw input."""
    document = _load(RELEASE_WORKFLOW)

    release_step = _find_step(
        _steps_by_job(document)["github-release"], name_contains="Create GitHub Release"
    )
    command = release_step["run"]

    assert 'gh release create "$VALIDATED_TAG"' in command
    assert "--verify-tag" in command
    job_env = document["jobs"]["github-release"]["env"]
    assert job_env["VALIDATED_TAG"] == "${{ needs.validate.outputs.tag }}"


def test_github_release_step_never_passes_a_full_ref_to_gh_release_create() -> None:
    """The gh release create invocation never receives refs/tags/... directly."""
    document = _load(RELEASE_WORKFLOW)

    release_step = _find_step(
        _steps_by_job(document)["github-release"], name_contains="Create GitHub Release"
    )

    assert "refs/tags" not in release_step["run"]
    assert "$RELEASE_REF" not in release_step["run"]
    assert "inputs.ref" not in release_step["run"]


def test_github_release_job_assets_come_from_the_release_dist_artifact() -> None:
    """The GitHub Release attaches the exact artifact the build job uploaded, not a rebuild."""
    document = _load(RELEASE_WORKFLOW)

    steps = _steps_by_job(document)["github-release"]
    download_step = _find_step(steps, name_contains="Download")

    assert download_step["with"]["name"] == "release-dist"
    assert all("uv build" not in (step.get("run") or "") for step in steps)


def test_github_release_job_needs_both_validate_and_publish() -> None:
    """github-release reads validate's outputs directly and only runs after publish succeeds."""
    document = _load(RELEASE_WORKFLOW)

    needs = document["jobs"]["github-release"]["needs"]

    assert set(needs) == {"validate", "publish"}


def test_attestation_subject_path_uses_multiline_syntax_with_separate_globs() -> None:
    """subject-path lists wheel and sdist as separate lines, not one comma-joined string."""
    document = _load(RELEASE_WORKFLOW)

    attest_step = _find_step(
        _steps_by_job(document)["github-release"], name_contains="provenance attestation"
    )
    subject_path = attest_step["with"]["subject-path"]
    lines = [line for line in subject_path.splitlines() if line.strip()]

    assert lines == ["dist/*.whl", "dist/*.tar.gz"]
    assert "," not in subject_path


def test_attestation_does_not_attest_the_hash_manifest() -> None:
    """SHA256SUMS is a hash manifest, not a Python distribution, and is not attested."""
    document = _load(RELEASE_WORKFLOW)

    attest_step = _find_step(
        _steps_by_job(document)["github-release"], name_contains="provenance attestation"
    )

    assert "SHA256SUMS" not in attest_step["with"]["subject-path"]


def test_no_run_step_interpolates_raw_workflow_inputs_or_job_outputs() -> None:
    """Every run: step reaches inputs/outputs only through env:, never direct interpolation.

    ``env:``, ``with:``, and job-level fields may reference ``${{ inputs.* }}``/``${{ needs.* }}``
    freely -- only shell script text is a code-injection surface for an untrusted string value.
    """
    document = _load(RELEASE_WORKFLOW)

    for job_name, job in document["jobs"].items():
        for step in job.get("steps", []):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            assert "${{ inputs." not in run, f"{job_name}/{step.get('name')} interpolates inputs"
            assert "${{ needs." not in run, f"{job_name}/{step.get('name')} interpolates needs"


def test_quality_workflow_has_no_id_token_permission_anywhere() -> None:
    """Ordinary CI never requests an OIDC token; only the release workflow may."""
    document = _load(QUALITY_WORKFLOW)

    assert document["permissions"].get("id-token") != "write"
    for job in document["jobs"].values():
        job_permissions = job.get("permissions", {})
        assert job_permissions.get("id-token") != "write"


def test_quality_workflow_has_no_contents_write_permission_anywhere() -> None:
    """Ordinary CI never requests write access to repository contents."""
    document = _load(QUALITY_WORKFLOW)

    assert document["permissions"].get("contents") == "read"
    for job in document["jobs"].values():
        job_permissions = job.get("permissions", {})
        assert job_permissions.get("contents") != "write"


def test_quality_workflow_triggers_on_pull_request_and_main_push_only() -> None:
    """Ordinary CI runs on pull requests and pushes to main, never workflow_dispatch."""
    document = _load(QUALITY_WORKFLOW)

    triggers = _triggers(document)

    assert set(triggers) == {"pull_request", "push"}
    assert triggers["push"]["branches"] == ["main"]


def test_quality_workflow_does_not_reference_a_pypi_token_secret() -> None:
    """Ordinary CI never reads a PyPI API token from repository secrets."""
    document = _load(QUALITY_WORKFLOW)

    text = _all_run_and_with_text(document)

    assert "secrets.PYPI" not in text
    assert "PYPI_TOKEN" not in text
