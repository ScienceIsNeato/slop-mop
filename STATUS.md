# Project Status

## Active Branch: `feat/bogus-tests-redesign` — PR #37

Redesigned bogus test detection with `pytest.raises` support, plus gate-dodging check with `ConfigField.permissiveness` metadata.

### Current State

All 13 quality gates passing locally. All PR review comments resolved. CI running.

### What's in This Branch

- **Bogus test detection redesign**: Pattern-based detection of tests that always pass (empty bodies, bare asserts, trivially true conditions). Now supports `pytest.raises` context managers as legitimate test patterns.
- **Gate-dodging check**: Detects loosened quality gate configuration vs base branch. Uses `ConfigField.permissiveness` metadata (`higher_is_stricter` / `lower_is_stricter`) to compare old vs new config values. Supports numeric and string comparisons (e.g., complexity rank "C" → "F").
- **ConfigField.permissiveness**: All 15 check schemas (34 fields) annotated with permissiveness direction. Enables automated detection of configuration weakening.
- **100% coverage**: `gate_dodging.py` at 246/246 statements covered.

### Recent Commits

- `98ee221` — fix: correct permissiveness metadata for min_confidence and max_rank
- `47abbdd` — test: improve gate-dodging coverage to 100% and fix merge conflicts
- Previous: bogus test redesign, gate-dodging implementation, schema annotations
