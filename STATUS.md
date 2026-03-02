# Project Status

## Active Branch: `feat/swab-scour`

**Status: LOCAL — all 1167 tests pass** ✅

### Summary

Comprehensive gate rename, auto-generation system, `--self` flag removal, profile→level terminology cleanup, sparkline fix, and `sm status` redesign all complete.

### Latest Work: `sm status` redesign + gate fixes

**Three issues fixed from `sm status` output:**

1. **blind-deployment hardcoded path** — Gate hardcoded `scripts/deploy_app.sh`. Made `deploy_script` and `test_script` fully configurable via `.sb_config.json` with empty defaults. Gate skips gracefully when not configured.

2. **"No Laziness code detected" misleading skip reason** — `BaseCheck.skip_reason()` used category display name in generic message. Fixed default to "Not applicable to this project". Added `skip_reason()` override to `eslint_quick.py` that delegates to `JavaScriptCheckMixin`.

3. **`sm status` ran gates** — Fundamentally redesigned as a pure dashboard/observatory:
   - Removed ALL gate execution code (CheckExecutor, DynamicDisplay, remediation, verdict, etc.)
   - New sections: config summary, gate inventory (with historical results from timings.json + sparklines), recent history, hooks status
   - Always returns 0 (no pass/fail — it's an observatory)
   - Removed `level` positional arg and `--static` flag from parser
   - `sm init` now shows dashboard instead of running all gates

**Files changed**: `slopmop/checks/general/deploy_tests.py`, `slopmop/checks/javascript/eslint_quick.py`, `slopmop/checks/base.py`, `slopmop/cli/status.py` (full rewrite), `slopmop/sm.py`, `slopmop/cli/init.py`, `tests/unit/test_status.py` (full rewrite, 37 tests)

### Previous Work

- Profile→level terminology cleanup (~15 source files, ~3 test files)
- Sparkline/history fix for sub-millisecond gates
- Display refinements (category timing, gate sorting, progress bar)
- `--self` flag removal
- Auto-generation system for README gate tables
- Comprehensive gate rename (delimiter swap, file renames, category reassignments)

### Remaining

- AGENTS.md rebuild via `cursor-rules/build_agent_instructions.sh`
- Live testing of `sm status` dashboard output