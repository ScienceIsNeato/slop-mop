# Releasing Slop-Mop

slop-mop releases should optimize for **verification** over speed. The
mechanics are automated; the judgment call is still human.

## Release Flow

The primary release path is the GitHub Actions dispatcher: Actions →
**Release** → **Run workflow** from `main` with the desired bump type. That
single run performs the full release:

1. bump `pyproject.toml`
2. commit the version bump to `main`
3. run release quality gates
4. build and smoke-test the package
5. publish to PyPI
6. create the GitHub release

This requires the workflow token to be allowed to write the version-bump commit
to `main`. If branch protection blocks bot pushes, allow the Actions bot to
bypass protection for this release workflow.

The local release script remains available as a PR-based fallback:

```bash
./scripts/release.sh patch
./scripts/release.sh minor
./scripts/release.sh major
```

The fallback script creates a release branch and PR that bumps `pyproject.toml`.
When that PR lands on `main`, the **Release** workflow still publishes because
the `pyproject.toml` version changed on `main`.

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
