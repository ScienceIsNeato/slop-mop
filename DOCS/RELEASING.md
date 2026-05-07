# Releasing Slop-Mop

slop-mop releases should optimize for **verification** over speed. The
mechanics are automated; the judgment call is still human.

## Release Flow

The primary release path is the GitHub Actions dispatcher: Actions →
**Release** → **Run workflow** from `main` with the desired bump type. That
manual run prepares the release through the protected-branch PR path:

1. bump `pyproject.toml`
2. create a release PR
3. run release quality gates against the release branch
4. build and smoke-test the package
5. merge the PR into `main`
6. publish the merged commit to PyPI
7. create the GitHub release

Merging ordinary PRs never publishes a release. The workflow is intentionally
manual-only, so a `pyproject.toml` version change on `main` is inert unless it
was created by the active **Release** workflow run.

The release job uses the default `GITHUB_TOKEN` with scoped write permissions
only for the release branch and PR. Branch protection still rejects direct pushes
to `main`, so the version bump reaches `main` only through the release PR.

If a manual release run is rerun before the release PR merges, the workflow
reuses the deterministic `release/vX.Y.Z` branch and updates the existing PR.
If it is rerun after the PR merges, it reuses the merge commit marked by the
original run instead of applying a second bump.

The local release script remains available for legacy/emergency version-bump PR
preparation from a developer machine, but it is not the normal publish path:

```bash
./scripts/release.sh patch
./scripts/release.sh minor
./scripts/release.sh major
```

The fallback script creates a release branch and PR that bumps `pyproject.toml`.
Merge alone will not publish, and the **Release** workflow computes its own bump
when manually dispatched. Prefer the workflow dispatcher for normal releases so
the bump, PR, merge, build, publish, and GitHub Release stay in one audited run.

## Fallback PR Checklist

Before merging a release-bump PR created by `scripts/release.sh`:

- `requirements.txt` is in sync with `pyproject.toml`
- config migrations and `DOCS/MIGRATIONS.md` are updated for any breaking
  config or gate-name changes
- the primary code-scanning gate is green on the release PR
- the unit-test coverage job published a sane coverage summary for the branch
- release notes accurately call out breaking changes and migration steps
- the version bump is the only intentional release trigger in the PR

## Build and Publish Verification

`release.yml` performs these checks before PyPI publication:

- build `sdist` and wheel
- verify the detected release version matches `pyproject.toml`
- run `twine check` on built artifacts
- install the built wheel into a clean virtualenv
- smoke-test the installed CLI (`sm --version`, `sm --help`, `sm init`)

The release should not publish if any of those checks fail.

## Post-Publish Checklist

After the workflow completes:

- verify the GitHub release tag matches the PyPI version
- verify the PyPI page shows the expected version and metadata
- verify a clean install of the published package works (`pipx install slopmop`)
- confirm the generated GitHub release notes are readable and complete
- if the release included a migration, confirm `sm upgrade` behavior against at
  least one older config snapshot

## Stability Expectations

See [DOCS/COMPATIBILITY.md](COMPATIBILITY.md) for the public compatibility and
support contract. This document stays focused on the mechanics of cutting and
verifying a release.
