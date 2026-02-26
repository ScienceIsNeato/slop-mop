# Project Status

## Active Branch: `fix/init-non-interactive-detection` → PR #48

**Status: PUSHED — awaiting CI on commit `5f84349`** ⏳

### PR #48 Summary (Consolidated)

9 commits pushed, 5 themes consolidated into one PR. Latest: `5f84349`.

### What's in This Branch

1. **Non-interactive terminal detection** (`sm init`): Auto-detect non-TTY stdin, fall back to non-interactive mode. Prevents hanging in CI/Docker/piped shells.
2. **README overhaul**: Neutral LLM-focused copy replacing GoT-themed opener. Badge cleanup, section reordering.
3. **Bolt-on usability**: `get_project_python()` now prefers `sys.executable` (slop-mop's Python with bundled tools) over system Python. Expanded `REQUIRED_TOOLS` to include py-lint dependencies.
4. **ToolContext enum**: Categorizes all 24 gates into PURE/SM_TOOL/PROJECT/NODE. Migrates security checks (bandit, detect-secrets, pip-audit) and complexity (radon) from `get_project_python()` to bare commands via `find_tool()`. PROJECT checks now warn-and-skip with actionable venv creation command when no project venv exists.
5. **Bug fixes (closes #49, #50, Bugbot comment)**: vulture whitelist argparse ordering, `sm config --json` flat→hierarchical normalization, radon added to REQUIRED_TOOLS + FileNotFoundError guard.

### Commits

- `3d4a566` — fix: auto-detect non-interactive terminal in sm init
- `b6a26a3` — fix: address PR #48 Bugbot findings
- `bd9157c` — fix: overhaul README opener, remove Tyrion branding
- `7517406` — fix: remove salesy copy from Quick Start and Loop
- `9758fd7` — fix: improve bolt-on usability for projects without a venv
- `b7acd08` — feat: add ToolContext enum for explicit tool resolution routing
- `f10b05d` — fix: move detection results after setup banner in sm init
- `9f13569` — fix: move tool_context after docstrings, restore sys.executable for bundled tools
- `5f84349` — fix: resolve #49, #50, and Bugbot radon detection comment

### Local Validation

- 1065 unit tests pass
- All 13 commit-profile quality gates green
- 5 Bugbot review threads resolved (all)
- Issues #49 and #50 referenced in commit (auto-close on merge)