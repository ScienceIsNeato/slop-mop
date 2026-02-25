# Project Status

<<<<<<< Updated upstream
## Active Branch: `chore/display-tweaks`

Post-v0.1.0 release polish: display improvements, Python 3.14 compatibility, README rewrite, category migration.

### What's in This Branch

- **Status waiting indicator**: `sm status` now shows all applicable gates upfront with animated `○`/`◌` "waiting" indicator before execution starts (was: gates only appeared when their thread started)
- **Python 3.14 compatibility**: Bumped dep minimums (semgrep>=1.140.0, black>=25.11.0, mypy>=1.17.0) to get cp314 wheel support. Dropped Python 3.9 (semgrep requires >=3.10). Updated classifiers, tool configs (black target-version, mypy python_version).
- **README rewrite**: Complete rewrite with philosophy-driven structure. Gates organized by LLM failure mode (overconfidence, deceptiveness, laziness, myopia). Fixed broken PyPI image (absolute URL). Added remediation path narrative (init → fix → hooks → agent freedom). Added PyPI version badge.
- **Category migration**: Migrated entire category system from language-based (python, javascript, security, quality) to flaw-based (overconfidence, deceptiveness, laziness, myopia). Single `GateCategory` enum source of truth in `checks/base.py`. `SlopmopConfig` now uses dynamic `categories: Dict[str, CategoryConfig]`. CLI, detection, help, init, config, status all updated. Tests and project instructions updated.

### Current State

All 832 unit tests passing. Category migration complete across 15 files: 11 source + 4 test files. Project instructions updated. Ready for commit.

### Category Migration Summary

**Source of truth**: `GateCategory` enum in `slopmop/checks/base.py`
**Categories**: overconfidence (💯), deceptiveness (🎭), laziness (🦥), myopia (👓), general (🔧), pr (🔀)
**Gate naming**: `{category}:{short-name}` (e.g., `laziness:py-lint`, `overconfidence:py-tests`)

**Source files changed** (11):
1. `checks/base.py` — Added `from_key()` classmethod to `GateCategory`
2. `core/config.py` — Removed duplicate `GateCategory`; re-exports from `checks/base.py`; `LanguageConfig` → `CategoryConfig`; `SlopmopConfig` dynamic categories
3. `cli/config.py` — `VALID_CATEGORIES` derived from `GateCategory` enum
4. `cli/help.py` — `_show_all_gates` groups dynamically by category
5. `cli/init.py` — `_disable_non_applicable` uses prefix-based gate disabling; `_apply_user_config` uses `category:gate` format
6. `cli/detection.py` — `_recommend_gates` returns flaw-based names
7. `cli/status.py` — Removed legacy category keys from `_CATEGORY_ORDER`
8. `core/executor.py` — Fixed stale comment
9. `reporting/display/state.py` — Fixed stale comment
10. `checks/constants.py` — Fixed stale docstring
11. `checks/quality/complexity.py` — Fixed stale docstring

**Test files changed** (4):
1. `test_cli.py` — `_deep_merge` test fixture uses flaw-based keys
2. `test_sm_cli.py` — Config fixtures, parser tests, detection test (`"overconfidence:js-types"`)
3. `test_generate_config.py` — Config fixture uses flaw-based key
4. `test_result.py` — `CheckDefinition` test fixtures use flaw-based gate names

**Docs updated**: `.github/instructions/project-slop-mop.instructions.md`
=======
## Current Work: feat/friction-fixes-and-improvements branch — PR #23

### Latest: Merged PR #22 into PR #23

**Summary:**
- Consolidated two open PRs (#22 and #23) into a single PR (#23)
- All 12 quality gates pass
- All 7 PR review comments addressed and resolved
- PR #22 closed with comment explaining the merge

### Combined changes now in PR #23:

**From original PR #23 (six friction points):**
1. `sm` wrapper: cd to project root before exec
2. `python:lint-format`: respect include_dirs; skip hidden dirs
3. `javascript:types` added to commit and pr profiles
4. `setup.sh`: auto-build find-duplicate-strings tool
5. `setup.sh`: arithmetic trap exit 1 fix
6. `setup.sh`: suppress husky noise

**Merged from PR #22:**
- Prioritize project-local venvs over VIRTUAL_ENV
- npm_install_flags support for React Native projects
- sm wrapper fallback to system Python for JS-only projects
- venv detection priority updates

**Additional fixes for PR review comments:**
- setup.sh: Add npm/npx availability check before build
- setup.sh: Capture subshell exit status with `|| true` for graceful failure
- lint_format.py: Use `--extend-exclude` instead of `--exclude` for flake8
- lint_format.py: Add `__pycache__` and `.*` (hidden dirs) to exclude list
- lint_format.py: Soften docstring about hidden dir scanning

### Status:
- CI checks running on PR #23
- PR #22 closed
- Waiting for CI to complete
>>>>>>> Stashed changes
