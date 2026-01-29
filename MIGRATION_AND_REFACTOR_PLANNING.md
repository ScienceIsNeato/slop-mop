# Migration and Refactor Planning: Quality Gate Infrastructure

## Executive Summary

This document outlines the migration of quality gate infrastructure from `course_record_updater` (specifically `scripts/ship_it.py` and `scripts/maintAInability-gate.sh`) into a standalone, language-agnostic, bolt-on code validation framework called **slopbucket**.

## Source Analysis

### Current State (course_record_updater)

| File | Lines | Purpose |
|------|-------|---------|
| `scripts/ship_it.py` | 2784 | Python orchestrator with parallel execution, PR integration |
| `scripts/maintAInability-gate.sh` | 2230 | Bash implementation of individual checks |

### Key Problems with Current Implementation

1. **Dual-language complexity**: Business logic split between Python and Bash
2. **Tight coupling**: Hardcoded paths, project-specific assumptions
3. **Redundancy**: Many checks implemented in both files
4. **Security**: Shell script execution without comprehensive command validation
5. **Maintainability**: 5000+ lines across two paradigms makes debugging painful

### Checks Currently Implemented

| Check ID | Shell Flag | Description | Implementation |
|----------|------------|-------------|----------------|
| `python-lint-format` | `--python-lint-format` | black, isort, flake8 | Shell |
| `js-lint-format` | `--js-lint-format` | ESLint, Prettier | Shell |
| `python-static-analysis` | `--python-static-analysis` | mypy, imports | Shell |
| `python-unit-tests` | `--python-unit-tests` | pytest | Shell |
| `python-coverage` | `--python-coverage` | pytest-cov 80% | Shell |
| `python-new-code-coverage` | `--python-new-code-coverage` | diff-cover | Shell |
| `js-tests` | `--js-tests` | Jest | Shell |
| `js-coverage` | `--js-coverage` | Jest coverage | Shell |
| `security` | `--security` | bandit, semgrep, safety | Shell |
| `security-local` | `--security-local` | bandit, semgrep (no network) | Shell |
| `complexity` | `--complexity` | radon/xenon | Python |
| `duplication` | `--duplication` | jscpd | Shell |
| `integration` | `--integration-tests` | pytest integration | Shell |
| `e2e` | `--e2e` | Playwright | Shell |
| `smoke` | `--smoke-tests` | Selenium | Shell |
| `frontend-check` | `--frontend-check` | Quick UI validation | Shell |
| `sonar-analyze` | `--sonar-analyze` | SonarCloud upload | Shell |
| `sonar-status` | `--sonar-status` | SonarCloud fetch | Shell |
| `template-validation` | N/A | Jinja2 syntax | Python |

### Check Aliases (Groups)

| Alias | Checks Included |
|-------|-----------------|
| `commit` | lint-format, static-analysis, unit-tests, coverage, complexity |
| `pr` | All checks |
| `integration` | lint-format, unit-tests, integration |
| `smoke` | lint-format, unit-tests, smoke |
| `full` | All + security (full) |

---

## Target Architecture (slopbucket)

### Design Principles

1. **SOLID Compliance**
   - Single Responsibility: Each class has one reason to change
   - Open/Closed: Add new checks without modifying existing code
   - Liskov Substitution: All checks implement common interface
   - Interface Segregation: Minimal interfaces for each concern
   - Dependency Inversion: Depend on abstractions, not concretions

2. **Pure Python Implementation**
   - No shell script layer
   - Secure subprocess handling with command validation
   - OS-agnostic design (macOS default, Linux/Windows support)

3. **Language/Repo Agnostic**
   - Auto-detect project type (Python, JS, mixed)
   - Configuration-driven check selection
   - No hardcoded paths or assumptions

4. **AI-Focused Error Reporting**
   - Fail fast with clear, actionable messages
   - Show exact failure location and fix suggestions
   - Minimize cognitive load for automated agents

### Module Structure

```
slopbucket/
├── setup.py                    # Entry point: python setup.py --help
├── pyproject.toml              # Package configuration
├── README.md                   # User documentation
├── MIGRATION_AND_REFACTOR_PLANNING.md
├── slopbucket/                 # Main package
│   ├── __init__.py
│   ├── __main__.py             # CLI entry: python -m slopbucket
│   ├── cli.py                  # Argument parsing, help text
│   ├── core/
│   │   ├── __init__.py
│   │   ├── executor.py         # Parallel check execution engine
│   │   ├── registry.py         # Check registration and discovery
│   │   ├── result.py           # CheckResult, CheckStatus types
│   │   └── config.py           # Configuration loading/validation
│   ├── checks/                 # Check implementations
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract base check class
│   │   ├── python/
│   │   │   ├── __init__.py
│   │   │   ├── lint_format.py  # black, isort, flake8
│   │   │   ├── static_analysis.py  # mypy
│   │   │   ├── tests.py        # pytest
│   │   │   ├── coverage.py     # pytest-cov, diff-cover
│   │   │   ├── security.py     # bandit, semgrep, safety
│   │   │   └── complexity.py   # radon
│   │   ├── javascript/
│   │   │   ├── __init__.py
│   │   │   ├── lint_format.py  # ESLint, Prettier
│   │   │   ├── tests.py        # Jest
│   │   │   └── coverage.py     # Jest coverage
│   │   └── general/
│   │       ├── __init__.py
│   │       ├── duplication.py  # jscpd
│   │       └── secrets.py      # detect-secrets
│   ├── subprocess/
│   │   ├── __init__.py
│   │   ├── runner.py           # Secure subprocess execution
│   │   ├── validator.py        # Command whitelist/validation
│   │   └── timeout.py          # Timeout handling
│   ├── reporting/
│   │   ├── __init__.py
│   │   ├── console.py          # Terminal output formatting
│   │   ├── summary.py          # Final summary generation
│   │   └── ai_friendly.py      # AI-optimized error messages
│   └── utils/
│       ├── __init__.py
│       ├── detection.py        # Project type detection
│       ├── logging.py          # Logging configuration
│       └── paths.py            # Path resolution utilities
├── tests/                      # Self-test suite
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_executor.py
│   │   ├── test_registry.py
│   │   ├── test_subprocess_validator.py
│   │   └── test_checks/
│   │       ├── test_python_lint.py
│   │       └── ...
│   └── integration/
│       ├── test_self_validation.py  # Run slopbucket against itself
│       └── test_end_to_end.py
├── config/
│   └── default.toml            # Default configuration
└── docs/
    ├── USAGE.md
    ├── CONFIGURATION.md
    └── ADDING_CHECKS.md
```

---

## Class Design

### Core Abstractions

```python
# slopbucket/checks/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Callable

class CheckStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"

@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    duration: float
    output: str = ""
    error: Optional[str] = None
    fix_suggestion: Optional[str] = None

class BaseCheck(ABC):
    """Abstract base class for all quality checks."""

    def __init__(self, config: dict):
        self.config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this check."""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name with emoji."""
        pass

    @property
    def depends_on(self) -> List[str]:
        """List of check names this check depends on."""
        return []

    @abstractmethod
    def is_applicable(self, project_root: str) -> bool:
        """Return True if this check applies to the current project."""
        pass

    @abstractmethod
    def run(self, project_root: str) -> CheckResult:
        """Execute the check and return result."""
        pass

    def can_auto_fix(self) -> bool:
        """Return True if this check can auto-fix issues."""
        return False

    def auto_fix(self, project_root: str) -> bool:
        """Attempt to auto-fix issues. Return True if successful."""
        return False
```

### Subprocess Security Layer

```python
# slopbucket/subprocess/validator.py
from typing import List, Set
from pathlib import Path

class CommandValidator:
    """Validates and sanitizes commands before subprocess execution.

    Security-focused design:
    - Whitelist of allowed executables
    - No shell=True execution
    - Path traversal prevention
    - Environment variable sanitization
    """

    ALLOWED_EXECUTABLES: Set[str] = {
        # Python tools
        "python", "python3", "pip", "pip3",
        "black", "isort", "flake8", "pylint", "mypy",
        "pytest", "coverage", "radon", "bandit", "semgrep", "safety",
        "diff-cover", "autoflake",
        # JavaScript tools
        "node", "npm", "npx",
        # Git
        "git",
        # General
        "timeout", "find", "wc",
    }

    def validate(self, command: List[str]) -> bool:
        """Validate command is safe to execute."""
        if not command:
            return False

        executable = Path(command[0]).name
        if executable not in self.ALLOWED_EXECUTABLES:
            raise SecurityError(f"Executable not in whitelist: {executable}")

        # Check for shell injection patterns
        dangerous_patterns = [";", "&&", "||", "|", "`", "$(" , "$("]
        for arg in command:
            for pattern in dangerous_patterns:
                if pattern in arg:
                    raise SecurityError(f"Dangerous pattern in argument: {pattern}")

        return True
```

### Check Registry

```python
# slopbucket/core/registry.py
from typing import Dict, List, Type
from slopbucket.checks.base import BaseCheck

class CheckRegistry:
    """Registry for discovering and managing available checks."""

    def __init__(self):
        self._checks: Dict[str, Type[BaseCheck]] = {}
        self._aliases: Dict[str, List[str]] = {}

    def register(self, check_class: Type[BaseCheck]) -> None:
        """Register a check class."""
        instance = check_class({})
        self._checks[instance.name] = check_class

    def register_alias(self, alias: str, check_names: List[str]) -> None:
        """Register a check alias (group)."""
        self._aliases[alias] = check_names

    def get_checks(self, names: List[str], config: dict) -> List[BaseCheck]:
        """Get check instances by name, expanding aliases."""
        expanded = []
        for name in names:
            if name in self._aliases:
                expanded.extend(self._aliases[name])
            else:
                expanded.append(name)

        return [self._checks[n](config) for n in expanded if n in self._checks]
```

---

## Method Migration Map

### From ship_it.py

| Original Method | Target Location | Notes |
|-----------------|-----------------|-------|
| `run_subprocess()` | `slopbucket/subprocess/runner.py` | Add validation layer |
| `start_subprocess()` | `slopbucket/subprocess/runner.py` | Background execution |
| `CheckDef` | `slopbucket/core/result.py` | Renamed to `CheckDefinition` |
| `CheckStatus` | `slopbucket/core/result.py` | Keep as-is |
| `CheckResult` | `slopbucket/core/result.py` | Add fix_suggestion field |
| `QualityGateExecutor` | `slopbucket/core/executor.py` | Refactor to use registry |
| `_run_complexity_analysis()` | `slopbucket/checks/python/complexity.py` | Standalone check class |
| `_run_template_validation()` | `slopbucket/checks/python/templates.py` | Standalone check class |
| `check_pr_comments()` | `slopbucket/integrations/github.py` | Optional module |
| `check_ci_status()` | `slopbucket/integrations/github.py` | Optional module |
| `generate_pr_issues_report()` | `slopbucket/reporting/pr_report.py` | Optional module |
| `main()` | `slopbucket/cli.py` | Simplified entry point |

### From maintAInability-gate.sh

| Original Function/Section | Target Location | Notes |
|---------------------------|-----------------|-------|
| Environment variable check | `slopbucket/utils/detection.py` | Auto-detect, don't require |
| `check_venv()` | `slopbucket/utils/detection.py` | Warning only |
| Black formatting | `slopbucket/checks/python/lint_format.py` | `PythonLintFormatCheck.run_black()` |
| Isort formatting | `slopbucket/checks/python/lint_format.py` | `PythonLintFormatCheck.run_isort()` |
| Flake8 check | `slopbucket/checks/python/lint_format.py` | `PythonLintFormatCheck.run_flake8()` |
| Mypy check | `slopbucket/checks/python/static_analysis.py` | `PythonStaticAnalysisCheck` |
| Pytest execution | `slopbucket/checks/python/tests.py` | `PythonTestsCheck` |
| Coverage analysis | `slopbucket/checks/python/coverage.py` | `PythonCoverageCheck` |
| Bandit scan | `slopbucket/checks/python/security.py` | `PythonSecurityCheck.run_bandit()` |
| Semgrep scan | `slopbucket/checks/python/security.py` | `PythonSecurityCheck.run_semgrep()` |
| Safety scan | `slopbucket/checks/python/security.py` | `PythonSecurityCheck.run_safety()` |
| Detect-secrets | `slopbucket/checks/general/secrets.py` | `SecretsCheck` |
| Radon complexity | `slopbucket/checks/python/complexity.py` | `PythonComplexityCheck` |
| ESLint | `slopbucket/checks/javascript/lint_format.py` | `JavaScriptLintFormatCheck` |
| Prettier | `slopbucket/checks/javascript/lint_format.py` | `JavaScriptLintFormatCheck` |
| Jest tests | `slopbucket/checks/javascript/tests.py` | `JavaScriptTestsCheck` |
| Jest coverage | `slopbucket/checks/javascript/coverage.py` | `JavaScriptCoverageCheck` |
| jscpd duplication | `slopbucket/checks/general/duplication.py` | `DuplicationCheck` |
| SonarCloud analyze | `slopbucket/integrations/sonarcloud.py` | Optional module |
| SonarCloud status | `slopbucket/integrations/sonarcloud.py` | Optional module |
| Smoke tests | `slopbucket/checks/general/smoke.py` | Project-specific, optional |
| Summary report | `slopbucket/reporting/summary.py` | `SummaryReporter` |

---

## TDD Implementation Plan

### Phase 1: Core Infrastructure (Test First)

```python
# tests/unit/test_subprocess_validator.py
def test_allows_whitelisted_executable():
    validator = CommandValidator()
    assert validator.validate(["python", "-m", "pytest"]) == True

def test_rejects_unknown_executable():
    validator = CommandValidator()
    with pytest.raises(SecurityError):
        validator.validate(["rm", "-rf", "/"])

def test_rejects_shell_injection():
    validator = CommandValidator()
    with pytest.raises(SecurityError):
        validator.validate(["python", "-c", "import os; os.system('rm -rf /')"])
```

### Phase 2: Check Base Classes

```python
# tests/unit/test_base_check.py
def test_check_result_dataclass():
    result = CheckResult(
        name="test",
        status=CheckStatus.PASSED,
        duration=1.5,
        output="All good"
    )
    assert result.name == "test"
    assert result.status == CheckStatus.PASSED

def test_base_check_abstract():
    with pytest.raises(TypeError):
        BaseCheck({})  # Cannot instantiate abstract class
```

### Phase 3: Individual Checks

```python
# tests/unit/test_checks/test_python_lint.py
def test_lint_format_detects_python_project(tmp_path):
    (tmp_path / "setup.py").write_text("# setup")
    check = PythonLintFormatCheck({})
    assert check.is_applicable(str(tmp_path)) == True

def test_lint_format_skips_non_python(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    check = PythonLintFormatCheck({})
    assert check.is_applicable(str(tmp_path)) == False
```

### Phase 4: Self-Validation Test

```python
# tests/integration/test_self_validation.py
def test_slopbucket_passes_own_checks():
    """The ultimate test: slopbucket must pass its own quality gates."""
    from slopbucket.core.executor import Executor
    from slopbucket.core.registry import default_registry

    executor = Executor(default_registry)
    results = executor.run_checks(
        project_root=".",
        check_names=["commit"]  # Run commit-level checks
    )

    failed = [r for r in results if r.status == CheckStatus.FAILED]
    assert len(failed) == 0, f"Self-validation failed: {[f.name for f in failed]}"
```

---

## Configuration Schema

```toml
# config/default.toml
[slopbucket]
version = "1.0.0"

[checks]
# Enable/disable specific checks
enabled = ["python-lint-format", "python-tests", "python-coverage"]
disabled = []

# Coverage thresholds
[checks.python-coverage]
threshold = 80
fail_under = true

[checks.python-new-code-coverage]
threshold = 80
compare_branch = "main"

[checks.complexity]
max_rank = "C"  # Fail on D or worse

# Check aliases
[aliases]
commit = ["python-lint-format", "python-static-analysis", "python-tests", "python-coverage"]
pr = ["commit", "security", "complexity"]
quick = ["python-lint-format"]

# Subprocess security
[subprocess]
timeout_default = 120  # seconds
timeout_max = 600

# Reporting
[reporting]
verbose = false
fail_fast = true
show_fix_suggestions = true
```

---

## Implementation Timeline

### Sprint 1: Foundation (Current Focus)
- [x] Create planning document
- [ ] Implement `slopbucket/core/result.py`
- [ ] Implement `slopbucket/subprocess/validator.py`
- [ ] Implement `slopbucket/subprocess/runner.py`
- [ ] Write tests for above

### Sprint 2: Check Infrastructure
- [ ] Implement `slopbucket/checks/base.py`
- [ ] Implement `slopbucket/core/registry.py`
- [ ] Implement `slopbucket/core/executor.py`
- [ ] Write tests for above

### Sprint 3: Python Checks
- [ ] Implement `slopbucket/checks/python/lint_format.py`
- [ ] Implement `slopbucket/checks/python/tests.py`
- [ ] Implement `slopbucket/checks/python/coverage.py`
- [ ] Write tests for above

### Sprint 4: CLI and Self-Validation
- [ ] Implement `slopbucket/cli.py`
- [ ] Implement `setup.py` entry point
- [ ] Self-validation test passes
- [ ] Documentation

### Sprint 5: course_record_updater Migration
- [ ] Add slopbucket as submodule
- [ ] Remove ship_it.py and maintAInability-gate.sh
- [ ] Update CI/CD configuration
- [ ] Verify all existing checks still work

---

## Risk Mitigation

1. **Compatibility**: Keep check names identical to ease migration
2. **Performance**: Parallel execution from day one
3. **Rollback**: Keep old scripts in git history, easy to revert
4. **Testing**: Self-validation ensures dogfooding

---

## Success Criteria

1. `python setup.py --help` provides accurate, comprehensive help
2. `python setup.py --checks commit` passes on slopbucket itself
3. All existing course_record_updater checks have equivalents
4. PR is green with no outstanding comments
5. Documentation covers all usage scenarios
