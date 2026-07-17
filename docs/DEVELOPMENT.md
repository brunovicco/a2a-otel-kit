# Development guide

## Setup

```bash
uv sync --frozen
```

## Run checks

```bash
uv run python scripts/quality_gate.py
```

The optional SDK contract is checked weekly and on every change across Python 3.13 and 3.14,
using both the lowest direct and highest bounded resolutions. Run
`uv run python scripts/validate_sdk_compatibility.py` after changing an optional SDK range;
public extras and development dependencies must describe the same interval.

## Collector integration

The Compose file is a local/CI receipt fixture, not a production deployment:

```bash
install -d -m 0777 .collector-receipts
install -m 0666 /dev/null .collector-receipts/traces.jsonl
docker compose -f compose.collector.yml up -d
A2A_OTEL_KIT_COLLECTOR_ENDPOINT=http://127.0.0.1:4318/v1/traces \
A2A_OTEL_KIT_COLLECTOR_RECEIPT_FILE=.collector-receipts/traces.jsonl \
uv run pytest --no-cov -m integration tests/integration/test_collector_otlp.py
docker compose -f compose.collector.yml down --volumes --remove-orphans
```

The test passes only after finding its service and span names in the receipt file. Always run the
final `down` command, including after failures.

## Building and verifying distribution artifacts

```bash
uv build --out-dir dist
uv run python scripts/verify_release_artifacts.py --dist-dir dist
```

`uv build` produces a wheel and an sdist from the current working tree; the build is not tied to
any specific commit or tag. `scripts/verify_release_artifacts.py` never builds anything itself -
it only inspects whatever is already in `--dist-dir`, so it always verifies the exact bytes a
caller intends to publish. It checks:

- the wheel contains every expected module and `py.typed`;
- the sdist contains `README.md`, `LICENSE`, `pyproject.toml`, and the full `src`/`tests` tree;
- `METADATA`/`PKG-INFO` report the expected name, version, `License-Expression: MIT`,
  `Requires-Python`, and the `a2a`/`mcp` extras;
- the wheel installs cleanly into three isolated, temporary virtual environments (base, `[a2a]`,
  `[mcp]`) and each required import succeeds with a guard that fails the run if any smoke-test
  import attempts to open a network socket.

Pass `--skip-smoke-test` to skip the three isolated-venv installs when iterating on metadata only;
CI always runs the full check. This script is intentionally separate from
`scripts/quality_gate.py` - it verifies distributable artifacts, not source-tree quality, and
needs a prior `uv build` step the quality gate does not perform.

### Build backend

`[build-system].requires` pins an exact Hatchling version (`hatchling==1.31.0`, verified against
live PyPI) rather than a range. `uv build` resolves the build backend in an isolated environment
that `uv.lock` does not constrain the way it constrains ordinary project dependencies - `uv.lock`
has no Hatchling entry at all, confirmed by inspecting it after a `uv lock` run - so an unpinned or
ranged backend could silently pick up a new Hatchling release between two builds of the same
commit. uv also supports `uv build --build-constraints <file>` to additionally pin a build
backend's own transitive dependencies; this project does not use it today because pinning
Hatchling itself is sufficient for the current `[tool.hatch.build...]` configuration, but it is a
reasonable next step if a stricter guarantee is ever needed.

To upgrade the pin deliberately: check the new version on PyPI, confirm it still supports this
project's Python range and `[tool.hatch.build...]` configuration (in particular PEP 639 license
metadata, supported since Hatchling 1.27), bump the exact version in `pyproject.toml`, run
`uv build` and `scripts/verify_release_artifacts.py` locally, and let the normal quality gate and
`build-and-verify` CI job confirm nothing regressed.

Pinning the build backend narrows one source of build-to-build variation, but this project does
not claim byte-for-byte **reproducible** builds: source tree, interpreter version/build, platform,
and installed system libraries can all still vary between machines. Absent a repeated-build
comparison that actually demonstrates identical output hashes, describe what this project does as
a **controlled and verified build** - pinned inputs, inspected output - not a reproducible one.

## Releasing

Releases are published to PyPI through `.github/workflows/release.yml` using [PyPI Trusted
Publishing](https://docs.pypi.org/trusted-publishers/) and GitHub OIDC - there is no PyPI API
token stored anywhere in this repository or its GitHub configuration.

**`v0.3.0` is tagged in git but must never be published to PyPI.** It was cut before this
project's release tooling existed, so its tree has no `LICENSE`, no PEP 639 license metadata, and
not even `release.yml` itself; publishing it would ship a non-compliant package, and its tag
cannot be amended without moving it, which is forbidden (see "Why tags must never be moved"
below). PyPI publication began with `v0.3.1`. All current and future releases follow the
"Cutting a release" process below.

### What a release actually is

- A **git tag** (`vX.Y.Z`, annotated, created and pushed by a maintainer) marks the exact commit a
  release is built from. Creating the tag does not publish anything by itself.
- A **GitHub Release** is a human-readable wrapper around that tag, with release notes and
  attached assets (wheel, sdist, `SHA256SUMS`, and a build-provenance attestation). It is created
  by the workflow only after PyPI publication succeeds.
- **PyPI publication** is the actual `pip`/`uv install`-able artifact upload. It is irreversible in
  the sense that a published version's files can never be re-uploaded (see "Rollback" below).

These three steps are ordered on purpose: tag → build → verify → publish to PyPI → GitHub Release.
A GitHub Release is never created for a version that failed to publish.

### Trusted Publisher configuration (maintainer, external to this repository)

The project and its Trusted Publisher already exist. If the publisher must be audited or
recreated, open the `a2a-otel-kit` project publishing settings on PyPI and use these exact values:

| Field | Value |
|---|---|
| PyPI Project Name | `a2a-otel-kit` |
| Owner | `brunovicco` |
| Repository name | `a2a-otel-kit` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

On GitHub, the repository environment must be named exactly `pypi`. Required reviewers are
recommended so every publish needs explicit human approval before `release.yml`'s `publish` job
runs. Do not add a PyPI token to this environment - Trusted Publishing needs none.

Both configurations must match `release.yml` exactly (repository, workflow filename, environment
name) or PyPI will reject the OIDC token and the `publish` job will fail closed.

### Cutting a release

1. On `main`, with a clean working tree, set `version` in `pyproject.toml` to the new release
   version and update `CHANGELOG.md` (move the `[Unreleased]` entries under a new `## [X.Y.Z] -
   YYYY-MM-DD` heading, leaving an empty `[Unreleased]` section in place). Commit and merge this
   to `main` through the normal PR/quality-gate flow.
2. Tag the resulting commit on `main` with an **annotated** tag and push it:

   ```bash
   git tag -a vX.Y.Z -m "Release X.Y.Z"
   git push origin vX.Y.Z
   ```

   Never create a lightweight tag (`git tag vX.Y.Z` without `-a`) - `release.yml` rejects it.
3. Dispatch the release workflow, from the GitHub UI (**Actions → release → Run workflow**) or:

   ```bash
   gh workflow run release.yml --ref vX.Y.Z -f ref=refs/tags/vX.Y.Z -f version=X.Y.Z
   ```

   `ref` and `version` are independent inputs and both are validated against the tag commit's
   `pyproject.toml`; a mismatch, a non-tag ref, a lightweight tag, or a dirty tree all fail the
   `validate` job before anything is built.
4. `validate` peels the tag to its commit SHA and publishes that SHA (and the normalized short tag
   name, e.g. `vX.Y.Z`) as job outputs. Every later job checks out that SHA directly - never the
   raw `ref` input again - and independently re-verifies the tag still resolves to that same SHA
   before doing anything privileged, so a tag moved after validation (accidentally or maliciously)
   is caught rather than silently built or published.
5. The workflow builds once from that commit, verifies the exact built artifacts, waits for the
   `pypi` environment approval, publishes via Trusted Publishing, and only then creates the GitHub
   Release - using the validated short tag name (`gh release create vX.Y.Z --verify-tag`, never
   `refs/tags/vX.Y.Z`) - with the wheel, sdist, `SHA256SUMS`, and a build-provenance attestation
   attached. No step rebuilds the package after `build` runs; `publish` and `github-release`
   download and reuse the exact artifacts `build` already verified.

### Why tags must never be moved

PyPI treats a published version's files as permanent: once `X.Y.Z` is uploaded, that exact set of
bytes can never be replaced, even by re-running the workflow against a tag whose content changed
after the fact. Moving or force-recreating a tag after it has been used (or could have been used)
for a release breaks that guarantee silently - a consumer who pinned `a2a-otel-kit==X.Y.Z` would
have no way to know the code behind that version changed. `release.yml` also depends on the tag
being annotated and immutable to validate that "the tag commit contains the matching package
version" means anything at all. If a tagged commit turns out to be wrong, cut a new patch version
and tag instead of moving the existing tag.

### Rollback and yanking

PyPI does not support deleting or overwriting a published file. If a published version is broken:

1. **Yank it**: from `https://pypi.org/manage/project/a2a-otel-kit/releases/`, use the release's
   Options menu to mark it [yanked](https://docs.pypi.org/project-management/yanking/) with a
   reason. A yanked release stays installable by an exact pin (`==X.Y.Z`) but is skipped by
   dependency resolvers doing a fresh install, so existing lockfiles keep working while new
   installs avoid it.
2. **Publish a fix** as a new, higher version (e.g. `X.Y.(Z+1)`) through the normal tag → workflow
   flow above. There is no PyPI mechanism to "replace" `X.Y.Z` in place.
3. The corresponding GitHub Release and tag are left in place as a historical record; do not
   delete the tag (see above). Edit the GitHub Release notes to point at the fixed version if
   useful for consumers.

### What remains manual

- Bumping `version` in `pyproject.toml` and updating `CHANGELOG.md` before tagging (deliberately
  not automated, so a release always corresponds to a reviewed PR).
- Creating and pushing the annotated tag.
- Dispatching the workflow with the correct `ref`/`version` inputs.
- Approving the `pypi` environment gate.
- Yanking a broken release on PyPI, and deciding when to do so.
- Repairing the PyPI Trusted Publisher or GitHub environment configuration if either changes.

## Container

```bash
docker build -t a2a-otel-kit .
docker run --rm a2a-otel-kit
```

`Dockerfile` is a multi-stage, uv-based build: a `builder` stage installs the locked
dependencies and builds the package, then only the resulting virtualenv and source are copied
into a slim, non-root runtime image. The shipped `CMD` is a placeholder - this harness is
framework-agnostic and does not assume an ASGI app, CLI, or worker loop. Replace it with the
project's real entrypoint. Adjust `.dockerignore` if new top-level files or directories need to
be excluded from the build context.

## Local configuration

Copy `.env.example` only when the application supports local dotenv loading. Never commit `.env` or real credentials.

## Claude Code

- Run `/memory` to confirm loaded instructions.
- Run `/hooks` to inspect configured hooks.
- Run `claude doctor` from the shell for a read-only installation and configuration check. Reserve
  interactive `/doctor` for cases that may need guided repair, and review its requested commands.
- Use `/plan-change` before complex work.
- Use `/quality-gate` before completion.
- Use `/prepare-pr` to produce a reviewable PR description.

### Isolating riskier changes in a worktree

For a larger or harder-to-reverse change, add `isolation: worktree` to
`.claude/agents/python-implementer.md`'s frontmatter before delegating the change. The subagent
then works from a temporary git worktree branched off the default branch instead of editing the
working tree directly; the worktree is cleaned up automatically if it makes no changes. This is
not the harness default because it changes where edits land - add it deliberately for a specific
change you want to inspect before merging into your working tree, then remove it again, rather
than leaving it on for routine, well-scoped work.
