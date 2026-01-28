"""
Configuration — Check definitions, profiles, and runtime settings.

Profiles are the user-facing interface: ``commit``, ``pr``, ``full``, etc.
Each profile expands to an ordered list of check names that the runner
will execute.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set


@dataclass
class CheckDef:
    """Definition of a single check."""

    name: str
    module_path: str  # e.g. "slopbucket.checks.python_format"
    class_name: str  # e.g. "PythonFormatCheck"
    description: str = ""
    language: str = "python"  # python, javascript, any
    category: str = "format"  # format, lint, tests, coverage, security, complexity


@dataclass
class RunnerConfig:
    """Runtime orchestration settings."""

    parallel: bool = True
    max_workers: int = 4
    fail_fast: bool = True
    verbose: bool = False
    timeout_secs: int = 900  # 15 minutes per check
    working_dir: Optional[str] = None


# =============================================================================
# Check Registry — every check slopbucket knows about
# =============================================================================

CHECK_REGISTRY: Dict[str, CheckDef] = {
    "python-format": CheckDef(
        name="python-format",
        module_path="slopbucket.checks.python_format",
        class_name="PythonFormatCheck",
        description="Black + isort + autoflake (auto-fixes applied)",
        language="python",
        category="format",
    ),
    "python-lint": CheckDef(
        name="python-lint",
        module_path="slopbucket.checks.python_lint",
        class_name="PythonLintCheck",
        description="Flake8 critical errors (E9, F63, F7, F82, F401)",
        language="python",
        category="lint",
    ),
    "python-types": CheckDef(
        name="python-types",
        module_path="slopbucket.checks.python_type_check",
        class_name="PythonTypeCheck",
        description="Mypy strict type checking",
        language="python",
        category="lint",
    ),
    "python-tests": CheckDef(
        name="python-tests",
        module_path="slopbucket.checks.python_tests",
        class_name="PythonTestsCheck",
        description="Pytest with coverage generation",
        language="python",
        category="tests",
    ),
    "python-coverage": CheckDef(
        name="python-coverage",
        module_path="slopbucket.checks.python_coverage",
        class_name="PythonCoverageCheck",
        description="Coverage threshold (80% global)",
        language="python",
        category="coverage",
    ),
    "python-diff-coverage": CheckDef(
        name="python-diff-coverage",
        module_path="slopbucket.checks.python_coverage",
        class_name="PythonDiffCoverageCheck",
        description="Coverage on changed files only (80%)",
        language="python",
        category="coverage",
    ),
    "python-complexity": CheckDef(
        name="python-complexity",
        module_path="slopbucket.checks.python_complexity",
        class_name="PythonComplexityCheck",
        description="Radon cyclomatic complexity (max rank C)",
        language="python",
        category="complexity",
    ),
    "python-security": CheckDef(
        name="python-security",
        module_path="slopbucket.checks.python_security",
        class_name="PythonSecurityCheck",
        description="Bandit + semgrep + detect-secrets + safety",
        language="python",
        category="security",
    ),
    "python-security-local": CheckDef(
        name="python-security-local",
        module_path="slopbucket.checks.python_security",
        class_name="PythonSecurityLocalCheck",
        description="Bandit + semgrep + detect-secrets (no network)",
        language="python",
        category="security",
    ),
    "python-duplication": CheckDef(
        name="python-duplication",
        module_path="slopbucket.checks.python_duplication",
        class_name="PythonDuplicationCheck",
        description="jscpd code duplication (max 5%)",
        language="python",
        category="lint",
    ),
    "js-format": CheckDef(
        name="js-format",
        module_path="slopbucket.checks.js_format",
        class_name="JSFormatCheck",
        description="ESLint + Prettier (auto-fixes applied)",
        language="javascript",
        category="format",
    ),
    "js-tests": CheckDef(
        name="js-tests",
        module_path="slopbucket.checks.js_tests",
        class_name="JSTestsCheck",
        description="Jest test runner",
        language="javascript",
        category="tests",
    ),
    "js-coverage": CheckDef(
        name="js-coverage",
        module_path="slopbucket.checks.js_coverage",
        class_name="JSCoverageCheck",
        description="Jest coverage threshold (80% lines)",
        language="javascript",
        category="coverage",
    ),
    "template-validation": CheckDef(
        name="template-validation",
        module_path="slopbucket.checks.template_validation",
        class_name="TemplateValidationCheck",
        description="Jinja2 template syntax validation",
        language="any",
        category="lint",
    ),
    "smoke": CheckDef(
        name="smoke",
        module_path="slopbucket.checks.smoke_check",
        class_name="SmokeCheck",
        description="Smoke tests (Selenium, requires running server)",
        language="python",
        category="tests",
    ),
    "e2e": CheckDef(
        name="e2e",
        module_path="slopbucket.checks.e2e_check",
        class_name="E2ECheck",
        description="E2E browser tests (Playwright, requires running server)",
        language="python",
        category="tests",
    ),
    "integration": CheckDef(
        name="integration",
        module_path="slopbucket.checks.integration_check",
        class_name="IntegrationCheck",
        description="Integration tests (database-backed, tests/integration/)",
        language="python",
        category="tests",
    ),
    "frontend-check": CheckDef(
        name="frontend-check",
        module_path="slopbucket.checks.frontend_check",
        class_name="FrontendCheck",
        description="Quick frontend validation (ESLint errors-only)",
        language="javascript",
        category="lint",
    ),
    "python-new-code-coverage": CheckDef(
        name="python-new-code-coverage",
        module_path="slopbucket.checks.python_coverage",
        class_name="PythonNewCodeCoverageCheck",
        description="New-code coverage gate (80%, CI-oriented)",
        language="python",
        category="coverage",
    ),
}

# =============================================================================
# Profiles — named check groups
# =============================================================================

PROFILES: Dict[str, List[str]] = {
    "commit": [
        "python-format",
        "python-lint",
        "python-types",
        "python-tests",
        "python-coverage",
        "python-complexity",
        "js-format",
        "js-tests",
        "js-coverage",
        "template-validation",
    ],
    "pr": [
        "python-format",
        "python-lint",
        "python-types",
        "python-tests",
        "python-coverage",
        "python-diff-coverage",
        "python-new-code-coverage",
        "python-complexity",
        "python-security",
        "python-duplication",
        "js-format",
        "js-tests",
        "js-coverage",
        "frontend-check",
        "template-validation",
    ],
    "security-local": [
        "python-security-local",
    ],
    "security": [
        "python-security",
    ],
    "format": [
        "python-format",
        "js-format",
    ],
    "lint": [
        "python-lint",
        "python-types",
    ],
    "tests": [
        "python-tests",
        "python-coverage",
        "js-tests",
        "js-coverage",
    ],
    "integration": [
        "python-format",
        "python-lint",
        "python-tests",
        "integration",
    ],
    "smoke": [
        "python-format",
        "python-lint",
        "python-tests",
        "smoke",
    ],
    "e2e": [
        "e2e",
    ],
    "full": list(CHECK_REGISTRY.keys()),
}

PROFILE_DESCRIPTIONS: Dict[str, str] = {
    "commit": "Fast pre-commit validation (~2-3 min, parallel)",
    "pr": "Full PR validation before merge (all checks)",
    "security-local": "Security scan without network calls",
    "security": "Full security audit (includes dependency scanning)",
    "format": "Auto-fix formatting (Python + JS)",
    "lint": "Static analysis (flake8 + mypy)",
    "tests": "Test suite + coverage enforcement",
    "integration": "Database-backed integration tests (requires DATABASE_URL)",
    "smoke": "Smoke tests (Selenium, requires running server on TEST_PORT)",
    "e2e": "End-to-end Playwright tests (requires server on E2E port)",
    "full": "Maximum validation (everything)",
}


def resolve_checks(
    check_names: List[str],
) -> List[CheckDef]:
    """Resolve check names/profiles into an ordered list of CheckDefs.

    Accepts a mix of profile names and individual check names.
    Deduplicates while preserving order.

    Args:
        check_names: List of profile names or check names.

    Returns:
        Ordered list of unique CheckDef objects.
    """
    seen: Set[str] = set()
    result: List[CheckDef] = []

    for name in check_names:
        # Expand profiles
        if name in PROFILES:
            expanded = PROFILES[name]
        elif name in CHECK_REGISTRY:
            expanded = [name]
        else:
            # Try common aliases
            aliases = {
                "python-lint-format": ["python-format", "python-lint"],
                "js-lint-format": ["js-format"],
                "python-static-analysis": ["python-types"],
                "python-unit-tests": ["python-tests"],
                "js-lint": ["js-format"],
                "coverage": ["python-coverage"],
            }
            expanded = aliases.get(name, [name])

        for check_name in expanded:
            if check_name in seen:
                continue
            if check_name in CHECK_REGISTRY:
                seen.add(check_name)
                result.append(CHECK_REGISTRY[check_name])

    return result
