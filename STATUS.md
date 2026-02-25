# Project Status

## Active Branch: `fix/v0.3.0-release-bugs`

Fixing three bugs reported after v0.3.0 release when run on course-record-updater project.

### Current State

All 13 quality gates passing locally. Ready for PR.

### What's in This Branch

- **Nested function false positives fixed**: `_TestAnalyzer` now tracks `_function_depth` to skip nested `def test_*()` inside test functions. Pytest only discovers module-level functions and direct class methods — nested function definitions (e.g. helper functions named `test_endpoint` inside a decorator test) are NOT test cases.
- **`self.assert*()` recognition**: `_has_assertion_mechanism` now detects unittest/Django TestCase assertion methods (`self.assertEqual()`, `self.assertTrue()`, `self.assertRaises()`, `self.assertRedirects()`, etc.).
- **`find-duplicate-strings` whitelisted**: Added to `ALLOWED_EXECUTABLES` in subprocess validator.
- **Fail-fast hang fix**: Executor now uses `shutdown(wait=True)` in fail-fast path so the atexit handler becomes a no-op. Added early stop-event check in `_run_single_check` so newly-submitted checks short-circuit immediately. Extracted "Skipped due to fail-fast" to `_SKIP_FAIL_FAST` constant.
- **13 new tests** covering nested function handling, self.assert* recognition, async nested functions, whitelist, and executor stop-event short-circuit.
