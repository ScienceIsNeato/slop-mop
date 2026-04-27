# CI

Run slop-mop in CI the same way you run it locally: install it, check out enough
history for git-aware gates, then run the gate command.

## GitHub Actions template

```yaml
name: slop-mop

on:
  pull_request:
  push:
    branches: [main]

jobs:
  swab:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: python -m pip install "slopmop[all]"
      - run: sm swab
```

The `fetch-depth: 0` line matters. Some gates compare against git history or
the PR base branch. A shallow checkout can make those gates fail with missing
revision errors.

## Coverage badges

Slop-mop's Python test gate writes `coverage.xml` when it runs the pytest path.
The coverage gates read that same file; they do not publish it anywhere by
themselves.

If you want a coverage badge, upload `coverage.xml` to a public coverage
reporter after `sm swab` or `sm scour` runs. This repo uploads it to Codecov in
the primary workflow and authenticates the upload with GitHub OIDC.

Keep the upload best-effort. The primary gate should block on slop-mop findings,
not on a coverage service outage. If `coverage.xml` is not produced, skip the
upload and let the slop-mop verdict own the check result.

This repo's own workflow is
[.github/workflows/slopmop-sarif.yml](../.github/workflows/slopmop-sarif.yml).

## PR follow-up

After CI finishes, run:

```bash
sm buff
```

`buff` checks CI status, unresolved review threads, and the next step in the PR
loop.