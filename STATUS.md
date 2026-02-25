# Project Status

## Active Branch: `feat/release-script-and-js-expect`

Two features: release automation script + eslint expect-expect check.

### Current State

All 13 quality gates passing locally. Ready for commit.

### What's in This Branch

- **Release script** (`scripts/release.sh`): Lightweight release automation — takes `patch|minor|major`, reads current version from pyproject.toml, computes bumped version, creates `release/vX.Y.Z` branch, commits version change, pushes, opens PR with changelog. Paper trail for every release.
- **Prepare Release workflow** (`.github/workflows/prepare-release.yml`): CI wrapper for the release script — `workflow_dispatch` with choice input, uses `github-actions[bot]` identity.
- **JS eslint expect-expect check** (`slopmop/checks/javascript/eslint_expect.py`): New `deceptiveness:js-expect-assert` gate that uses eslint-plugin-jest's `expect-expect` rule for AST-based assertion enforcement. Complements the regex-based `js-bogus-tests` check. Supports `additional_assert_functions`, `exclude_dirs`, and `max_violations` config. Added to `commit` and `pr` profiles.
- **17 new tests** for the eslint expect-expect check covering pass/fail/skip/timeout/config error/custom assert functions/dir exclusion/JSON parsing.
