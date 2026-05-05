# Releasing Slop-Mop

slop-mop releases should optimize for **verification** over speed. The
mechanics are automated; the judgment call is still human.

## Release Flow

There are two supported entry points:

```bash
./scripts/release.sh patch
./scripts/release.sh minor
./scripts/release.sh major
```

Or the equivalent manual GitHub Actions dispatcher in `prepare-release.yml`.

Both paths create a release branch and PR that bumps `pyproject.toml`. After
that PR lands on `main`, publish with Actions → **Release to PyPI** → **Run
workflow** from `main`. You may leave the version input blank to publish the
current `pyproject.toml` version, or fill it in as a guardrail; the workflow
fails if the input does not match `pyproject.toml`.

The release workflow also runs automatically when `pyproject.toml` changes on
`main`, so the manual button is the explicit recovery path when you want to
rerun or double-check publishing from GitHub.

## Pre-Merge Checklist

Before merging a release-bump PR:

- `requirements.txt` is in sync with `pyproject.toml`
- config migrations and `DOCS/MIGRATIONS.md` are updated for any breaking
  config or gate-name changes
- the primary code-scanning gate is green on the release PR
- the unit-test coverage job published a sane coverage summary for the branch
- release notes accurately call out breaking changes and migration steps
- the version bump is the only intentional release trigger in the PR

## Build and Publish Verification

`release.yml` performs these checks before PyPI publication, whether it is
triggered automatically from `main` or manually from the GitHub Actions UI:

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
