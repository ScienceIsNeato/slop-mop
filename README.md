# Slopbucket

**AI-optimized code validation gate.** A bolt-on quality check framework designed to catch AI-generated slop before it reaches production.

## Philosophy

- **Fail fast** — Stop on the first real problem. Don't waste time on downstream checks.
- **Maximum signal, minimum noise** — Every failure comes with: what broke, why, and exactly how to fix it.
- **Auto-fix when possible** — Formatting, imports, lint — if it can be fixed automatically, it is.
- **AI-first output** — Designed for LLM consumption. No ambiguity. No digging. Actionable in one read.
- **Secure by default** — All subprocess calls go through an allowlist. No shell injection possible.

## Installation

Add as a git submodule to any repository:

```bash
git submodule add https://github.com/ScienceIsNeato/slopbucket.git slopbucket
```

Or clone directly for standalone use:

```bash
git clone https://github.com/ScienceIsNeato/slopbucket.git
cd slopbucket
pip install -r requirements.txt
```

## Usage

```bash
# See all available checks and profiles
python slopbucket/setup.py --help
python slopbucket/setup.py --list

# Fast pre-commit validation (parallel, fail-fast)
python slopbucket/setup.py --checks commit

# Full PR validation
python slopbucket/setup.py --checks pr

# Security audit only (no network)
python slopbucket/setup.py --checks security-local

# Individual checks
python slopbucket/setup.py --checks python-format python-lint
```

## Available Profiles

| Profile | Description |
|---------|-------------|
| `commit` | Fast pre-commit validation (~2-3 min, parallel) |
| `pr` | Full PR validation before merge |
| `security-local` | Security scan without network calls |
| `security` | Full security audit |
| `format` | Auto-fix formatting (Python + JS) |
| `lint` | Static analysis (flake8 + mypy) |
| `tests` | Test suite + coverage enforcement |
| `full` | Maximum validation (everything) |

## Available Checks

| Check | What It Does |
|-------|-------------|
| `python-format` | Black + isort + autoflake (auto-fixes applied) |
| `python-lint` | Flake8 critical errors (E9, F63, F7, F82, F401) |
| `python-types` | Mypy strict type checking |
| `python-tests` | Pytest with coverage generation |
| `python-coverage` | Global coverage threshold (80%) |
| `python-diff-coverage` | Coverage on changed files only |
| `python-complexity` | Radon cyclomatic complexity |
| `python-security` | Bandit + semgrep + detect-secrets + safety |
| `python-security-local` | Security without network |
| `python-duplication` | Code duplication detection |
| `js-format` | ESLint + Prettier |
| `js-tests` | Jest test runner |
| `js-coverage` | Jest coverage threshold |
| `template-validation` | Jinja2 template syntax |

## Architecture

```
setup.py                    <- Single CLI entry point
slopbucket/
+-- runner.py               <- Parallel orchestration, fail-fast
+-- config.py               <- Profiles, check registry
+-- result.py               <- Result types, terminal formatting
+-- subprocess_guard.py     <- Secure allowlist-based execution
+-- base_check.py           <- BaseCheck ABC (interface contract)
+-- check_discovery.py      <- Dynamic check class loading
+-- checks/                 <- Individual check implementations
    +-- python_format.py
    +-- python_lint.py
    +-- python_type_check.py
    +-- python_tests.py
    +-- python_coverage.py
    +-- python_complexity.py
    +-- python_security.py
    +-- python_duplication.py
    +-- js_format.py
    +-- js_tests.py
    +-- js_coverage.py
    +-- template_validation.py
```

## Running Slopbucket's Own Tests

```bash
cd slopbucket
pip install -r requirements.txt
pip install -r requirements-dev.txt
pytest tests/ -v
```

## Migration from ship_it.py

If you're migrating from the LoopCloser `ship_it.py` / `maintAInability-gate.sh` setup:

1. Add slopbucket as a submodule
2. Replace `python scripts/ship_it.py --checks <name>` with `python slopbucket/setup.py --checks <name>`
3. Legacy check aliases (`python-lint-format`, `python-unit-tests`, etc.) are supported for smooth transition
4. Remove `scripts/ship_it.py` and `scripts/maintAInability-gate.sh`

See `MIGRATION_AND_REFACTOR_PLANNING.md` for the complete mapping.

## License

MIT
