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
│   └── template_validation.py # Jinja2 template syntax check
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

---

## Check Profiles (Replaces ship_it.py aliases)

| Profile | Checks Included | Use Case |
|---------|-----------------|----------|
| `commit` | python-format, python-lint, python-types, python-tests, python-coverage, python-complexity, js-format, js-tests, js-coverage, template-check | Fast pre-commit (~3 min) |
| `pr` | All checks | Full PR validation before merge |
| `security-local` | python-security-bandit, python-security-semgrep, python-security-secrets | Quick security without network |
| `security` | security-local + python-security-safety | Full security audit |
| `integration` | python-format, python-lint, python-tests | Database integration focus |
| `smoke` | python-format, python-lint, python-tests, smoke | Server + browser tests |
| `full` | All checks | Maximum validation |
| `format` | python-format, js-format | Auto-fix only |
| `lint` | python-lint, python-types, js-lint | Static analysis |
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
- [ ] Implement subprocess_guard.py with tests
- [ ] Implement result.py with tests
- [ ] Implement config.py with tests
- [ ] Implement base_check.py and check_discovery.py with tests
- [ ] Implement runner.py with tests
- [ ] Implement cli.py (setup.py) with tests
- [ ] Implement python_format.py (black, isort, autoflake)
- [ ] Implement python_lint.py (flake8)
- [ ] Implement python_type_check.py (mypy)
- [ ] Implement python_tests.py (pytest)
- [ ] Implement python_coverage.py (coverage, diff-cover)
- [ ] Implement python_complexity.py (radon)
- [ ] Implement python_security.py (bandit, semgrep, detect-secrets, safety)
- [ ] Implement python_duplication.py (jscpd)
- [ ] Implement js_format.py (eslint, prettier)
- [ ] Implement js_tests.py (jest)
- [ ] Implement js_coverage.py (jest coverage)
- [ ] Implement template_validation.py
- [ ] Implement profiles.py (commit, pr, full, etc.)
- [ ] Run slopbucket against itself — all checks pass
- [ ] Create slopbucket PR
- [ ] Update course_record_updater to use submodule
- [ ] Create course_record_updater PR
- [ ] Verify both PRs are green

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
