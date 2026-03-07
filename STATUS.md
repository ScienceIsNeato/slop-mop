# Project Status

## Design Documents

- **NEXT_PHASE.md**: Three-workstream architectural brief for the next phase of slop-mop:
  1. Two-tier check architecture (Foundation vs Diagnostic) with CheckRole enum
  2. Didactic gate output (Diagnosis → Prescription → Verification)
  3. Unified output adapter layer (RunReport + adapters replacing ad-hoc branching in _run_validation())

## Active Branch: `custom-gates-and-beta-hardening`

**Status: LOCAL — all 1327 tests pass** ✅

### Summary

Custom gates feature, output polish, PR category removal, and comprehensive custom gate test coverage.

### Latest Work: Strategic planning — model critique synthesis → 3 feature issues

**Round 4 changes (this session):**

1. **Model critique analysis** — Fact-checked 20+ specific claims from two external model analyses against the actual codebase. ~40% of Model A's claims were factually wrong (e.g., "gates run in fixed order" — actually dual-lane parallel scheduler; "suppressions are binary" — actually multi-layered with transparency mechanisms; "SARIF creates feedback loop" — SARIF goes to Security tab, not PR review threads). Model B's analysis was more cautious and held up better.

2. **Synthesized 4 criticisms, removed 1 via counterargument** — Config conflict detection removed as out-of-scope. Gate-dodging already monitors target repo's .sb_config.json (confirmed in code). 3 valid criticisms survived.

3. **Filed 3 GitHub issues:**
   - **#76**: `sm swab --baseline <ref>` — Delta reporting for responsible triage. "Do no harm" onboarding mode. Sentry-style new-vs-pre-existing findings.
   - **#77**: Add `fix_strategy` field to `Finding` dataclass. Machine-extractable remediation instructions separate from human-readable message.
   - **#78**: Gates as teachers — systematic actionability audit. 52% of gates are semi-actionable; target ≥70% prescriptive. Philosophy: agents should cargo-cult to green because gate instructions encode domain knowledge.

### Previous Work: Custom gate tests + output polish + PR category removal

**Round 3 changes:**

1. **Emoji spacing fix** — `display_width()` in `renderer.py` counted zero-width chars (U+FE0E, U+FE0F, U+200B, U+200D, U+FEFF) as width 1 instead of 0, causing missing space between emoji and test name for skipped/warned gates. Fixed by adding zero-width char detection before `east_asian_width()` check.

2. **Move ignored-feedback to myopia** — Changed `PRCommentsCheck.category` from `GateCategory.PR` to `GateCategory.MYOPIA`. Updated all references across source, tests, CI workflow, README, AGENTS.md, cursor-rules, and .github/instructions files (`pr:ignored-feedback` → `myopia:ignored-feedback`).

3. **Remove PR category entirely** — Removed `PR = ("pr", "🔀", "Pull Request")` from `GateCategory` enum, `CATEGORY_ORDER`, `category_palette`, `_CATEGORY_ORDER`, `is_pr_check` special case in console reporter, and PR entries from readme_tables. Updated all affected tests.

4. **Custom gate unit tests (97 tests)** — Comprehensive tests for `_resolve_category`, `_resolve_level`, `_make_custom_check_class`, custom check `.run()`, `register_custom_gates` happy path, invalid input handling, and edge cases. Key discovery: `get_registry` must be patched at `slopmop.core.registry.get_registry` (not `slopmop.checks.custom.get_registry`) because it's imported inside the function body.

5. **Custom gate integration tests (12 tests)** — End-to-end tests with real `CheckRegistry` instances: passing/failing gates, file inspection, multiple independent gates, scour-level attribute verification, output capture, shell pipes, JSON config parsing, `is_custom_gate` attribute, cwd verification, mixed valid/invalid entries. Uses `get_check()` and `_check_classes` directly (not `get_checks(level=...)` which doesn't exist).

### Files Changed (Round 3)
- `slopmop/reporting/display/renderer.py` — zero-width char fix
- `slopmop/checks/base.py` — removed GateCategory.PR
- `slopmop/checks/pr/comments.py` — category → MYOPIA
- `slopmop/reporting/display/config.py` — removed "pr" from CATEGORY_ORDER
- `slopmop/reporting/display/colors.py` — removed "pr" from category_palette
- `slopmop/cli/status.py` — removed "pr" from _CATEGORY_ORDER
- `slopmop/reporting/console.py` — removed is_pr_check special case
- `slopmop/utils/readme_tables.py` — removed PR entries
- `.github/workflows/slopmop.yml` — pr:ignored-feedback → myopia:ignored-feedback
- `README.md` — removed PR Gates section
- `AGENTS.md` — updated references
- `.github/instructions/` — updated references
- `cursor-rules/.cursor/rules/` — updated references
- `tests/unit/test_pr_checks.py` — GateCategory.PR → MYOPIA
- `tests/unit/test_colors.py` — removed "pr" from category list
- `tests/unit/test_dynamic_display.py` — updated references
- `tests/unit/test_custom_gates.py` — NEW (97 tests)
- `tests/unit/test_custom_gates_integration.py` — NEW (12 tests)

### Previous Work (Rounds 1-2)
- Compact JSON schema, human output cleanup, custom gates docs
- Stale-docs migration, .pyc cache fix, format_time fast label fix
- Custom gate asterisk prefix indicator
- Sparkline visibility during running/pending checks
- Startup output compaction, footnote removal
- Failure output condensing, registration message removal
- Double newline fix, sparkline truncation fix, "Not run" section removal

### Groundhog Day Protocol: 80-Column PTY Constraint

**Status: COMPLETE** ✅

- Diagnosed VS Code agent terminal hardcoded 80-column pty
- 6 experiments proving COLUMNS, stty, fixedDimensions, xterm escapes all fail
- Key workaround: `command > /tmp/file.txt 2>&1` + `read_file` bypasses pty
- cursor-rules/path_management.mdc updated (propagates to ALL projects)
- .github/instructions/path_management.instructions.md updated
- AGENTS.md rebuilt with terminal constraint section
- RECURRENT_ANTIPATTERN_LOG.md updated with full analysis
- Removed ineffective `terminal.integrated.fixedDimensions` from VS Code settings
- slop-mop display layer already cooperates (60-char separators, truncation, DEFAULT_TERMINAL_WIDTH=80)

### Remaining
- Local validation via `sm validate commit` before committing

## 2026-03-07 Delta: Config UX + Display Name Polish

### Completed

1. **Fixed `sm config --show` regression**
  - Root cause: `cmd_config()` no longer checked `args.show`, so `--show` fell through to no-args usage output.
  - Fix: restored explicit `if args.show: return _show_config(...)` branch in `slopmop/cli/config.py`.

2. **Strengthened config behavior tests**
  - `tests/unit/test_sm_cli.py`:
    - Expanded `test_show_config` assertions to verify full gate list output appears.
    - Added `test_config_no_args_shows_usage_hints` to lock in new no-args UX and prevent `--show` regressions.

3. **Display-name updates finalized and reconciled with tests/docs**
  - Updated security gate display-name expectations in `tests/unit/test_security_checks.py` to match new labels.
  - Regenerated README gate tables after display-name changes:
    - `python scripts/generate_readme_tables.py --update`
    - Updated `README.md`.

### Validation

- `python -m pytest tests/unit/test_sm_cli.py tests/unit/test_result.py -q` → **106 passed**
- `sm config` and `sm config --show` smoke test → **behavior correct**
- `sm swab -g laziness:stale-docs --verbose` → **pass**
- `sm swab -g overconfidence:untested-code.py --verbose` → **pass**
- `sm swab --json --output-file .slopmop/last_swab.json` → **16 checks passed**

## 2026-03-07 Delta: README Caching Callout

### Completed

1. Added a new **Selective Gate Caching** subsection to `README.md` under
  the Levels/Time Budget area.
2. Documented that caching is fingerprint-based and selective per gate when
  checks declare scoped inputs, with project-wide fallback for conservative
  correctness.
3. Added explicit command examples for both cached runs and cold runs:
  - `sm swab`
  - `sm swab --no-cache`
4. Documented cache location: `.slopmop/cache.json`.

## 2026-03-07 Delta: Swabbing-Time Scheduler Fix

### Issue

- `--swabbing-time` runs were scheduling heavier timed gates early and skipping
  cheaper ones, which contradicted the README's fastest-first contract.

### Completed

1. Updated budget scheduling in `slopmop/core/executor.py`:
   - Replaced dual-lane heavy/light timed gate submission with
     **fastest-first timed submission** under active budget.
   - Kept no-budget behavior unchanged (longest-first for throughput).
   - Fixed slot handling so untimed gates are capped to available worker slots.

2. Updated and expanded scheduler tests in
   `tests/unit/test_executor_budget.py`:
   - Reworked dual-lane assertions to fastest-first expectations.
   - Added coverage for untimed slot capping.
   - Adjusted integration timing fixtures to still validate budget-expiry skips
     under fastest-first semantics.

3. Added early README pointer near Quick Start to selective caching section
   (`README.md`) in addition to the detailed subsection.

### Validation

- `python -m pytest tests/unit/test_executor_budget.py tests/unit/test_sm_cli.py tests/unit/test_security_checks.py -q` → **142 passed**
- Scenario smoke test: `sm config --swabbing-time 5 && sm swab --no-cache` now prioritizes cheaper timed gates and skips heavier ones first.
- Restored budget and full validation:
  - `sm config --swabbing-time 100`
  - `sm swab --json --output-file .slopmop/last_swab.json` → **16 checks passed**

## 2026-03-07 Delta: Budget-Aware Dual-Lane Packing

### Issue

- Fastest-first alone was too naive for constrained swab budgets.
- Desired behavior: keep one fast lane for short checks, use remaining lanes
  for longer checks, and pack as many checks as possible into projected time.

### Completed

1. Updated scheduler in `slopmop/core/executor.py`:
   - Restored/implemented a dual-lane timed scheduler under budget:
     - 1 fast lane pick (shortest fitting timed gate)
     - remaining heavy lanes picked via subset packing
   - Added projected-budget admission control:
     - budget left = `swabbing_time - elapsed - in_flight_expected`
     - if no projected room, defer timed submissions until next loop
   - Added `_choose_packed_subset()` helper with objective:
     - maximize count first, then maximize packed expected duration.
   - Kept dependency safety by scheduling only from ready gates
     (dependencies already satisfied by executor).

2. Updated tests in `tests/unit/test_executor_budget.py`:
   - Renamed expectations from fastest-first to dual-lane packing behavior.
   - Added projected-budget/in-flight guardrail test.
   - Updated selection expectations for fast-lane + heavy-pack outcomes.

3. Updated README time-budget wording to match actual scheduler semantics.

### Validation

- `python -m pytest tests/unit/test_executor_budget.py -q` → **18 passed**
- `python -m pytest tests/unit/test_executor_budget.py tests/unit/test_sm_cli.py tests/unit/test_security_checks.py -q` → **143 passed**
- Scenario smoke test:
  - `sm config --swabbing-time 5`
  - `sm swab --no-cache`
  - Observed 5.8s run with mixed fast-lane/heavy-lane selections and budget skips.
- Restored default budget + full run:
  - `sm config --swabbing-time 100`
  - `sm swab --json --output-file .slopmop/last_swab.json` → **16 checks passed**