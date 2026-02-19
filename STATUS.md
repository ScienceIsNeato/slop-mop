# Project Status

## Active Branch: `feat/dynamic-check-display`

PR #24 — brew-style dynamic terminal UI for `sm validate` / `sm status`.

### What's in This Branch

- **Dynamic display** (`DynamicDisplay`): live-updating TTY output with animated spinners, progress bars, ETA from persisted timings, and category-grouped headers
- **Timing persistence**: `.slopmop/timings.json` stores per-check historical averages; pruned after 30 days / 100 entries
- **Flaw-based taxonomy**: all checks now live under `overconfidence:`, `deceptiveness:`, `laziness:`, or `myopia:` instead of language/quality/security prefixes
- **Visual polish**: per-category progress bar colors, separate N/A vs disabled footer lines, BRIGHT_YELLOW laziness header
- **`--static` flag**: opt out of dynamic display for scripted/CI use
- **`--clear-history` flag**: wipe stored timings

### Current State

All quality gates passing. See open [PR #24](https://github.com/ScienceIsNeato/slop-mop/pull/24) for remaining review comments.
