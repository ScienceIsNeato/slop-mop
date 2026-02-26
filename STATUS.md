# Project Status

## Active Branch: `fix/init-non-interactive-detection` → PR #48

**Status: WORKING — ToolContext implementation complete, ready for commit** 🔧

### PR #48 Summary (Consolidated)

6 commits (5 pushed + 1 staged), 4 themes consolidated into one PR. Latest pushed: `9758fd7`.

### What's in This Branch

1. **Non-interactive terminal detection** (`sm init`): Auto-detect non-TTY stdin, fall back to non-interactive mode. Prevents hanging in CI/Docker/piped shells.
2. **README overhaul**: Neutral LLM-focused copy replacing GoT-themed opener. Badge cleanup, section reordering.
3. **Bolt-on usability**: `get_project_python()` now prefers `sys.executable` (slop-mop's Python with bundled tools) over system Python. Expanded `REQUIRED_TOOLS` to include py-lint dependencies.
4. **ToolContext enum** (new): Categorizes all 24 gates into PURE/SM_TOOL/PROJECT/NODE. Migrates security checks (bandit, detect-secrets, pip-audit) and complexity (radon) from `get_project_python()` to bare commands via `find_tool()`. PROJECT checks now warn-and-skip with actionable venv creation command when no project venv exists.

### Commits

- `3d4a566` — fix: auto-detect non-interactive terminal in sm init
- `b6a26a3` — fix: address PR #48 Bugbot findings
- `bd9157c` — fix: overhaul README opener, remove Tyrion branding
- `7517406` — fix: remove salesy copy from Quick Start and Loop
- `9758fd7` — fix: improve bolt-on usability for projects without a venv
- (staged) — feat: add ToolContext enum for explicit tool resolution routing

### Local Validation

- 1054 unit tests pass
- All 13 commit-profile quality gates green
- 4 Bugbot review threads resolved