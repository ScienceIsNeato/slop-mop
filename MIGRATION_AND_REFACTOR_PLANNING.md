# Slopbucket — Migration & Refactor Planning

## Origin & Motivation

Slopbucket is extracted from the LoopCloser (course_record_updater) repository's quality gate infrastructure. The original system comprised two monolithic files:

- `scripts/ship_it.py` (2,784 lines) — Python orchestrator that parallelizes checks
- `scripts/maintAInability-gate.sh` (2,230 lines) — Bash implementation of individual checks

Both files grew organically without a central design, resulting in duplicated logic, inconsistent interfaces, and a tightly-coupled dependency on a single host repository. This refactor decouples the validation infrastructure into a reusable, OS-agnostic, language-agnostic Python package.

---

## Architecture Overview

### Design Principles (SOLID Applied)

| Principle | Application |
|-----------|-------------|
| **Single Responsibility** | Each check class owns exactly one validation concern. The CLI owns argument parsing. The runner owns orchestration. |
| **Open/Closed** | New checks are added by subclassing `BaseCheck` — no modification to the runner or CLI required. |
| **Liskov Substitution** | All checks conform to the `BaseCheck` interface; the runner treats them identically. |
| **Interface Segregation** | `CheckConfig` carries only what a check needs. `RunnerConfig` carries only orchestration state. |
| **Dependency Inversion** | The runner depends on `BaseCheck` abstractions, not concrete classes. Check discovery is plugin-based via a registry. |

### Class Hierarchy

```
slopbucket/
├── cli.py                  # Entry point — argparse, command routing, --help
├── runner.py               # Orchestrator — parallel execution, fail-fast, result aggregation
├── config.py               # Configuration — CheckConfig, RunnerConfig, profiles (commit/pr/full)
├── result.py               # CheckResult, CheckStatus, summary formatting
├── subprocess_guard.py     # Secure subprocess wrapper — allowlist-based command execution
├── base_check.py           # BaseCheck ABC — interface every check must satisfy
├── check_discovery.py      # Registry — auto-discovers and loads check modules
├── checks/                 # Individual check implementations
│   ├── __init__.py         # Package init, exports all checks
│   ├── python_format.py    # Black + isort + autoflake
│   ├── python_lint.py      # Flake8 (critical errors only)
│   ├── python_type_check.py # Mypy
│   ├── python_tests.py     # Pytest with coverage generation
│   ├── python_coverage.py  # Coverage threshold enforcement (global + diff)
│   ├── python_complexity.py # Radon cyclomatic complexity
│   ├── python_security.py  # Bandit + semgrep + detect-secrets
│   ├── python_duplication.py # jscpd duplication detection
│   ├── js_format.py        # ESLint + Prettier
│   ├── js_tests.py         # Jest test runner
│   ├── js_coverage.py      # Jest coverage threshold
│   ├── template_validation.py # Jinja2 template syntax check
│   ├── smoke_check.py      # Selenium smoke tests (requires running server)
│   ├── e2e_check.py        # Playwright E2E tests (requires running server)
│   ├── integration_check.py # Database integration tests (requires DATABASE_URL)
│   └── frontend_check.py   # Quick ESLint errors-only frontend validation
├── profiles.py             # Predefined check groups (commit, pr, integration, smoke, full)
├── setup.py                # pip-installable entry point with comprehensive --help
└── tests/                  # Self-test suite (TDD-first)
    ├── test_cli.py
    ├── test_runner.py
    ├── test_subprocess_guard.py
    ├── test_check_discovery.py
    ├── test_config.py
    ├── test_result.py
    └── test_checks/        # Unit tests for each check module
```

### Execution Flow

```
CLI (setup.py / slopbucket CLI)
  │
  ▼
config.py → resolve profile → list of CheckDef objects
  │
  ▼
check_discovery.py → load check classes from checks/
  │
  ▼
runner.py → execute checks (parallel via ThreadPoolExecutor)
  │        → fail-fast on first failure (configurable)
  │        → collect CheckResult objects
  │
  ▼
result.py → format output (terminal-optimized, fail-first)
  │
  ▼
CLI → exit code (0 = all pass, 1 = any failure)
```

### Subprocess Security Model

All shell commands go through `subprocess_guard.py`:
- Maintains an **allowlist** of permitted executables
- Validates command arguments against injection patterns
- Rejects any command not explicitly registered
- Logs all subprocess invocations for audit trail
- No shell=True ever used (prevents shell injection)

---

## Source-to-Target Check Mapping

| Original Location | Check Name | Target Module | Migration Notes |
|-------------------|------------|---------------|-----------------|
| ship_it.py:run_single_check("black") → gate.sh | python-format | `checks/python_format.py` | Auto-fix preserved |
| ship_it.py:run_single_check("isort") → gate.sh | python-import-sort | `checks/python_format.py` | Combined with black |
| ship_it.py:run_single_check("autoflake") → gate.sh | python-unused-imports | `checks/python_format.py` | Combined with black |
| ship_it.py:run_single_check("flake8") → gate.sh | python-lint | `checks/python_lint.py` | Critical errors only (E9,F63,F7,F82,F401) |
| ship_it.py:run_single_check("mypy") → gate.sh | python-types | `checks/python_type_check.py` | Strict mode |
| ship_it.py:run_single_check("pytest") → gate.sh | python-tests | `checks/python_tests.py` | Parallel-safe |
| ship_it.py:run_single_check("coverage") → gate.sh | python-coverage | `checks/python_coverage.py` | 80% threshold |
| ship_it.py:run_single_check("diff-coverage") → gate.sh | python-diff-coverage | `checks/python_coverage.py` | diff-cover integration |
| ship_it.py:run_single_check("radon") → gate.sh | python-complexity | `checks/python_complexity.py` | Max rank C |
| ship_it.py:run_single_check("bandit") → gate.sh | python-security-bandit | `checks/python_security.py` | HIGH/MEDIUM only |
| ship_it.py:run_single_check("semgrep") → gate.sh | python-security-semgrep | `checks/python_security.py` | Auto-config |
| ship_it.py:run_single_check("detect-secrets") → gate.sh | python-security-secrets | `checks/python_security.py` | Baseline-based |
| ship_it.py:run_single_check("safety") → gate.sh | python-security-safety | `checks/python_security.py` | Optional (network) |
| ship_it.py:run_single_check("jscpd") → gate.sh | python-duplication | `checks/python_duplication.py` | 5% threshold |
| ship_it.py:run_single_check("eslint") → gate.sh | js-lint | `checks/js_format.py` | Auto-fix |
| ship_it.py:run_single_check("prettier") → gate.sh | js-format | `checks/js_format.py` | Combined with eslint |
| ship_it.py:run_single_check("jest") → gate.sh | js-tests | `checks/js_tests.py` | npm run test |
| ship_it.py:run_single_check("jest-coverage") → gate.sh | js-coverage | `checks/js_coverage.py` | 80% lines |
| ship_it.py:run_single_check("template-validation") | template-check | `checks/template_validation.py` | Jinja2 syntax |
| quality-gate.yml smoke-tests job | smoke | `checks/smoke_check.py` | Selenium, requires running server (TEST_PORT) |
| quality-gate.yml e2e-tests job | e2e | `checks/e2e_check.py` | Playwright, requires server (E2E port) |
| quality-gate.yml integration-tests job | integration | `checks/integration_check.py` | Database-backed, requires DATABASE_URL |
| ship_it.py `--checks frontend-check` | frontend-check | `checks/frontend_check.py` | Quick ESLint errors-only (~5s) |
| quality-gate.yml coverage-new-code job | python-new-code-coverage | `checks/python_coverage.py` | diff-cover, COMPARE_BRANCH-aware |

---

## Check Profiles (Replaces ship_it.py aliases)

| Profile | Checks Included | Use Case |
|---------|-----------------|----------|
| `commit` | python-format, python-lint, python-types, python-tests, python-coverage, python-complexity, js-format, js-tests, js-coverage, template-validation | Fast pre-commit (~3 min) |
| `pr` | All static checks + python-new-code-coverage + frontend-check | Full PR validation before merge |
| `security-local` | python-security-local | Quick security without network |
| `security` | python-security (bandit + semgrep + detect-secrets + safety) | Full security audit |
| `integration` | python-format, python-lint, python-tests, integration | Database-backed integration tests (requires DATABASE_URL) |
| `smoke` | python-format, python-lint, python-tests, smoke | Selenium smoke tests (requires running server on TEST_PORT) |
| `e2e` | e2e | Playwright E2E tests (requires server on E2E port) |
| `full` | All checks | Maximum validation |
| `format` | python-format, js-format | Auto-fix only |
| `lint` | python-lint, python-types | Static analysis |
| `tests` | python-tests, python-coverage, js-tests, js-coverage | Testing only |

---

## TDD Strategy for slopbucket

### Phase 1: Foundation (test-first)
1. Write `test_subprocess_guard.py` — verify allowlist enforcement, injection prevention
2. Write `test_result.py` — verify CheckResult formatting, status enum behavior
3. Write `test_config.py` — verify profile loading, check resolution
4. Implement the tested classes

### Phase 2: Core
1. Write `test_check_discovery.py` — verify plugin loading, BaseCheck conformance
2. Write `test_runner.py` — verify parallel execution, fail-fast, result collection
3. Write `test_cli.py` — verify argument parsing, --help output, exit codes
4. Implement the tested classes

### Phase 3: Checks (each follows test → implement)
1. For each check module in `checks/`:
   a. Write unit test mocking subprocess_guard
   b. Verify check correctly parses tool output
   c. Verify pass/fail determination logic
   d. Verify auto-fix behavior where applicable
   e. Implement the check

### Phase 4: Integration
1. Run slopbucket against itself (dogfooding)
2. Verify all checks pass on the slopbucket codebase
3. Fix any issues found

---

## Migration Checklist

- [x] Deep dive analysis of ship_it.py and maintAInability-gate.sh
- [x] Design class hierarchy and interface contracts
- [x] Document source-to-target mapping for every check
- [x] Implement subprocess_guard.py with tests (15 tests)
- [x] Implement result.py with tests (11 tests)
- [x] Implement config.py with tests (10 tests)
- [x] Implement base_check.py and check_discovery.py with tests (6 tests)
- [x] Implement runner.py with tests (6 tests)
- [x] Implement cli.py (setup.py) with tests (5 tests)
- [x] Implement python_format.py (black, isort, autoflake) + unit tests (6 tests)
- [x] Implement python_lint.py (flake8) + unit tests (5 tests)
- [x] Implement python_type_check.py (mypy) + unit tests (4 tests)
- [x] Implement python_tests.py (pytest) + unit tests (8 tests)
- [x] Implement python_coverage.py (coverage, diff-cover) + unit tests (8 tests)
- [x] Implement python_complexity.py (radon) + unit tests (5 tests)
- [x] Implement python_security.py (bandit, semgrep, detect-secrets, safety) + unit tests (11 tests)
- [x] Implement python_duplication.py (jscpd) + unit tests (3 tests)
- [x] Implement js_format.py (eslint, prettier) + unit tests (4 tests)
- [x] Implement js_tests.py (jest) + unit tests (4 tests)
- [x] Implement js_coverage.py (jest coverage) + unit tests (4 tests)
- [x] Implement template_validation.py + unit tests (4 tests)
- [x] Implement smoke_check.py (Selenium smoke tests) + unit tests (6 tests)
- [x] Implement e2e_check.py (Playwright E2E) + unit tests (6 tests)
- [x] Implement integration_check.py (database integration) + unit tests (6 tests)
- [x] Implement frontend_check.py (quick ESLint) + unit tests (5 tests)
- [x] Implement python-new-code-coverage check + unit tests (5 tests, including COMPARE_BRANCH resolution)
- [x] Fix python-diff-coverage to use COMPARE_BRANCH env var (was hardcoded origin/main)
- [x] Add wave-based parallel ordering to runner (coverage checks after tests)
- [x] Register all 19 checks in CHECK_REGISTRY
- [x] Differentiate smoke vs integration profiles (previously identical)
- [x] Run slopbucket against itself — commit profile passes (6 passed, 4 skipped, ~90% coverage)
- [x] Create slopbucket PR (#2)
- [x] Update course_record_updater to use submodule
- [x] Create course_record_updater PR (#56)
- [x] Fix coverage-new-code CI job to route through slopbucket
- [x] Fix YAML indentation errors in quality-gate.yml
- [ ] Verify both PRs are green (pending CI run)

---

## Server-Dependent Checks — Host CI Responsibility

Checks that require a running server or seeded database are implemented
as **orchestration checks**: slopbucket invokes pytest against the
appropriate test directory but does NOT manage server lifecycle.  The
host CI workflow is responsible for database seeding and server startup
before invoking slopbucket.

| Check | Requires | Env Vars | Graceful Skip When |
|-------|----------|----------|-------------------|
| `smoke` | Running server + Selenium | TEST_PORT or PORT | No tests/smoke/ dir, or no port configured |
| `e2e` | Running server + Playwright | LOOPCLOSER_DEFAULT_PORT_E2E or TEST_PORT | No tests/e2e/ dir, or no port, or no playwright |
| `integration` | Seeded database | DATABASE_URL | No tests/integration/ dir, or no DATABASE_URL |

**Profile mapping for legacy check names:**

| Old Name | New Equivalent |
|----------|----------------|
| `frontend-check` | `frontend-check` (registered check) |
| `smoke` | `smoke` (registered check + profile) |
| `python-unit-tests` | `python-tests` (alias registered) |
| `coverage` | `python-coverage` (alias registered) |
| `python-new-code-coverage` | `python-new-code-coverage` (registered check) |
| `security-local` | `python-security-local` (profile) |

**Intentionally not implemented:**

| Item | Rationale |
|------|-----------|
| SonarQube / sonar | Was never part of the active quality gate in course_record_updater |

---

## Key Design Decisions

1. **Pure Python** — No shell scripts. All subprocess calls go through the guarded wrapper.
2. **Parallel by default** — ThreadPoolExecutor with configurable worker count.
3. **Fail-fast** — First failure stops remaining checks in the batch (configurable).
4. **Auto-fix first** — Format checks run auto-fix before validation, reducing noise.
5. **Explicit output** — Every failure includes: what failed, why, and exactly how to fix it.
6. **AI-optimized output** — Designed for LLM consumption: structured, unambiguous, actionable.
7. **Plugin architecture** — Checks are discovered via the registry; adding new checks requires zero changes to core.
8. **Submodule-friendly** — Designed to be dropped into any repo as a git submodule. `setup.py` handles bootstrapping.
9. **Wave-ordered parallelism** — Coverage checks (Wave 2) run after test checks (Wave 1) to avoid race conditions on `.coverage` / `coverage.xml` artifacts.
10. **COMPARE_BRANCH-aware diff coverage** — Reads from COMPARE_BRANCH env → GITHUB_BASE_REF → origin/main. No hardcoded branch.
