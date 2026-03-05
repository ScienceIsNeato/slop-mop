# Project Status

## Active Branch: `custom-gates-and-beta-hardening`

**Status: LOCAL — all 1327 tests pass** ✅

### Summary

Custom gates feature, output polish, PR category removal, and comprehensive custom gate test coverage.

### Latest Work: Custom gate tests + output polish + PR category removal

**Round 3 changes (this session):**

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