# Project Status

## Active Branch: `chore/display-tweaks`

Post-v0.1.0 release polish: display improvements, Python 3.14 compatibility, README rewrite.

### What's in This Branch

- **Status waiting indicator**: `sm status` now shows all applicable gates upfront with animated `○`/`◌` "waiting" indicator before execution starts (was: gates only appeared when their thread started)
- **Python 3.14 compatibility**: Bumped dep minimums (semgrep>=1.140.0, black>=25.11.0, mypy>=1.17.0) to get cp314 wheel support. Dropped Python 3.9 (semgrep requires >=3.10). Updated classifiers, tool configs (black target-version, mypy python_version).
- **README rewrite**: Complete rewrite with philosophy-driven structure. Gates organized by LLM failure mode (overconfidence, deceptiveness, laziness, myopia). Fixed broken PyPI image (absolute URL). Added remediation path narrative (init → fix → hooks → agent freedom). Added PyPI version badge.

### Current State

All 832 unit tests passing. All 5 self-validation gates green. Ready for commit.

### Files Changed

1. `slopmop/cli/status.py` — Added pending callback for upfront gate display
2. `slopmop/reporting/display/config.py` — Added `WAITING_FRAMES` constant
3. `slopmop/reporting/display/dynamic.py` — Animated waiting indicator, extracted footer method, waiting count in footer
4. `tests/unit/test_dynamic_display.py` — Updated pending line assertion
5. `pyproject.toml` — Python >=3.10, dep bumps, classifiers, tool config updates
6. `README.md` — Complete rewrite with current nomenclature
7. `STATUS.md` — This file
