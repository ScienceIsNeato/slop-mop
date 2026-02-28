# Project Status

## Active Branch: `feat/swab-scour`

**Status: LOCAL — all tests pass, self-validation green, ready to push** ✅

### Summary

Replacing the `commit`/`pr` profile system with intrinsic gate-level metadata (`swab`/`scour`). New top-level commands `sm swab` (fast, every commit) and `sm scour` (thorough, PR-level). `sm validate` retained as deprecated shim. `--swabbing-time` flag added as preview (accepted but not enforced). `SkipReason` enum added for structured skip metadata. All `validate` terminology scrubbed from source and docs.

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
10. **All check docstrings** — `./sm validate <gate>` → `./sm swab -g <gate>`, `Re-validate:` → `Re-check:`
11. **`_register_aliases` refactored** — split into `_register_legacy_aliases` + `_register_aliases` to fix LOC lock
12. **`generate_base_config`** — removed `default_profile`
13. **SkipReason enum** — 6 structured skip reasons: FAIL_FAST, NOT_APPLICABLE, DISABLED, DEPENDENCY_FAILED, SUPERSEDED, TIME_BUDGET
14. **CheckResult.skip_reason** — `Optional[SkipReason]` field set by executor on all SKIPPED/NOT_APPLICABLE results
15. **Terminology cleanup** — all `validate` references removed from sm.py docstring, help.py, README

### Test Updates

- test_sm_cli.py — swab/scour parser tests, `--swabbing-time` tests, hook format tests, routing tests
- test_cli.py — `_print_next_steps` assertions updated
- test_console_reporter.py — next-step string updated, SkipReason-based skip code tests
- test_executor.py — SkipReason assertions for dependency-skip and inapplicable results
- test_generate_config.py — `default_profile` assertion removed
- test_status.py — fully updated (imports, parser, helpers, inventory, remediation)
- Integration tests — docker_manager default command, docstrings

### Validation

- 1061 unit tests pass
- 13 self-validation gates green (sm swab --self)
- CI workflows updated (sm scour --self, sm scour -g pr:comments)
- README fully updated (zero `validate` references remain)