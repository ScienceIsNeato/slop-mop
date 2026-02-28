# Project Status

## Active Branch: `feat/swab-scour`

**Status: LOCAL — all tests pass, self-validation green, ready to push** ✅

### Summary

Replacing the `commit`/`pr` profile system with intrinsic gate-level metadata (`swab`/`scour`). New top-level commands `sm swab` (fast, every commit) and `sm scour` (thorough, PR-level). `sm validate` removed — no backward compatibility. `--swabbing-time` flag fully implemented with pre-run budget filtering. `SkipReason` enum added for structured skip metadata. All `validate` terminology scrubbed from source and docs. "Not run" summary section added to output — every skipped check is listed with its reason.

### Core Changes

1. **GateLevel enum** (`SWAB`, `SCOUR`) as ClassVar on `BaseCheck` — 3 checks set to `SCOUR` (PRCommentsCheck, PythonDiffCoverageCheck, SecurityCheck)
2. **Registry** `get_gate_names_for_level()` — SCOUR returns all gates, SWAB filters scour-only
3. **Executor** superseded_by auto-filtering after dependency expansion
4. **validate.py** refactored — shared `_run_validation()`, `cmd_swab()`, `cmd_scour()`, deprecated `cmd_validate()`
5. **sm.py** — `_add_validation_flags()` shared helper with `--swabbing-time` flag, swab/scour parsers, routing
6. **status.py** — level-based gate resolution, renamed display functions/strings
7. **hooks.py** — maps legacy profiles to verbs, new `# Command: sm {verb}` format
8. **init.py** — `_print_next_steps()` references swab/scour
9. **console.py** — next-step remediation uses `./sm swab -g <gate>`, skip reason codes use `SkipReason` enum
10. **All check docstrings** — `./sm swab -g <gate>`, `Re-check:`
11. **`_register_aliases` refactored** — split into `_register_legacy_aliases` + `_register_aliases` to fix LOC lock
12. **`generate_base_config`** — removed `default_profile`, added `swabbing_time: 20`
13. **SkipReason enum** — 6 structured skip reasons: FAIL_FAST, NOT_APPLICABLE, DISABLED, DEPENDENCY_FAILED, SUPERSEDED, TIME_BUDGET
14. **CheckResult.skip_reason** — `Optional[SkipReason]` field set by executor on all SKIPPED/NOT_APPLICABLE results
15. **Terminology cleanup** — all `validate` references removed from sm.py docstring, help.py, README
16. **"Not run" summary section** — `ConsoleReporter._print_not_run_section()` lists all skipped/N/A checks with human-readable reasons (disabled, not applicable, time budget w/ est. duration, fail-fast, dependency failed, superseded); appears in both success and failure paths
17. **Executor records disabled/superseded checks** — previously filtered silently, now recorded as SKIPPED results with appropriate SkipReason so they appear in the summary
18. **laziness:config-debt gate** — `ConfigDebtCheck` detects three forms of config debt: (1) stale applicability — language gates disabled but language present, (2) disabled gates — items in `disabled_gates` top-level list, (3) exclude drift — `exclude_dirs` with source files. Always WARNED, never FAILED. Enabled in self-validation. 40 unit tests.

### Swabbing-Time Implementation

- **Pre-run budget filtering**: Gates with historical timing data sorted fastest-first; greedily accepted until budget exceeded; gates without timing data always run (to establish baseline)
- **No mid-run termination**: Once a gate starts running, it runs to completion (avoids noise from borderline timing)
- **Config integration**: `sm init` defaults to 20s; `sm config --swabbing-time N` to change; `<= 0` disables
- **Swab-only**: Time budgets only apply to swab runs; scour always runs all gates
- **executor.py**: `run_checks()` extended with `swabbing_time`/`timings` params; new `_apply_time_budget()` method
- **validate.py**: CLI flag → config fallback → profile check chain; loads timings via `load_timings()`

### Test Updates

- test_sm_cli.py — swab/scour parser tests, `--swabbing-time` tests (parser, config set, config disable), hook format tests, routing tests
- test_cli.py — `_print_next_steps` assertions updated
- test_console_reporter.py — next-step string updated, SkipReason-based skip code tests, 10 `TestNotRunSection` tests (disabled/N/A/time-budget/fail-fast labels, sort order, omit-when-empty, failure path)
- test_executor.py — SkipReason assertions for dependency-skip and inapplicable results; 9 `TestSwabbingTimeBudget` tests; disabled gate tests updated for SKIPPED result recording; fixed pre-existing bug in `test_disabled_gate_propagates_to_dependents` (mismatched mock names)
- test_generate_config.py — `default_profile` assertion removed
- test_status.py — fully updated (imports, parser, helpers, inventory, remediation)
- Integration tests — docker_manager default command, docstrings

### Validation

- 1116 unit tests pass
- 14 self-validation gates green (sm swab --self), including new config-debt
- CI workflows updated (sm scour --self, sm scour -g pr:comments)
- README fully updated (zero `validate` references remain)