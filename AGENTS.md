# AGENTS.md

## Cursor Cloud specific instructions

**Product:** Slop-Mop (`slopmop`) is a Python CLI tool that runs automated quality gates on AI-assisted codebases. The CLI command is `sm` (e.g., `sm swab`, `sm scour`, `sm status`). There are no servers, databases, or background services — it is a pure CLI tool.

**Activating the venv:** Always activate the virtualenv before running any Python or test commands:
```bash
source /workspace/venv/bin/activate
```

**Running tests:** `pytest tests/unit/ -v` runs the full unit test suite (1190 tests). Integration tests in `tests/integration/` require Docker and are not needed for routine development.

**Lint / type-check commands:** See `pyproject.toml` for tool configuration. Key commands:
- `black --check slopmop/ tests/` (formatting)
- `isort --check slopmop/ tests/` (import order)
- `flake8 slopmop/ tests/` (linting)
- `ruff check slopmop/` (linting)
- `mypy slopmop/` (type checking)
- `pyright slopmop/` (type checking)

**Self-validation:** The project dogfoods itself: `python -m slopmop.sm swab` runs all quality gates on the slopmop codebase. This is the primary "build and run" command.

**Gotcha — `python3.12-venv` system package:** The base VM image may not have `python3.12-venv` installed. The update script handles this automatically via `apt-get install`.

**Vendored Node.js tool:** `tools/find-duplicate-strings/` requires `npm install` (with `HUSKY=0` to suppress git-hook warnings). The build output (`lib/cli/index.js`) is checked in, so it only needs rebuilding if the TypeScript source changes.

**Config file:** Running `sm init` creates `.sb_config.json` in the project root. This file is gitignored and must be regenerated in fresh environments.

**pyright venvPath warning:** pyright may emit a warning about a non-existent venvPath from `pyrightconfig.json` (references the original author's local path). This is harmless and does not affect type-checking results.
