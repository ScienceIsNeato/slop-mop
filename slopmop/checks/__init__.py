"""Quality gate checks for slopmop.

This module provides registration for all available checks and aliases.
"""

from slopmop.core.registry import CheckRegistry, get_registry


def _register_python_checks(registry: CheckRegistry) -> None:
    """Register all Python-related checks."""
    from slopmop.checks.python.coverage import (
        PythonCoverageCheck,
        PythonDiffCoverageCheck,
        PythonNewCodeCoverageCheck,
    )
    from slopmop.checks.python.lint_format import PythonLintFormatCheck
    from slopmop.checks.python.static_analysis import PythonStaticAnalysisCheck
    from slopmop.checks.python.test_types import (
        E2ETestCheck,
        IntegrationTestCheck,
        SmokeTestCheck,
    )
    from slopmop.checks.python.tests import PythonTestsCheck
    from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

    registry.register(PythonLintFormatCheck)
    registry.register(PythonTestsCheck)
    registry.register(PythonCoverageCheck)
    registry.register(PythonDiffCoverageCheck)
    registry.register(PythonNewCodeCoverageCheck)
    registry.register(PythonStaticAnalysisCheck)
    registry.register(PythonTypeCheckingCheck)
    registry.register(SmokeTestCheck)
    registry.register(IntegrationTestCheck)
    registry.register(E2ETestCheck)


def _register_javascript_checks(registry: CheckRegistry) -> None:
    """Register all JavaScript-related checks."""
    from slopmop.checks.javascript.coverage import JavaScriptCoverageCheck
    from slopmop.checks.javascript.eslint_quick import FrontendCheck
    from slopmop.checks.javascript.lint_format import JavaScriptLintFormatCheck
    from slopmop.checks.javascript.tests import JavaScriptTestsCheck
    from slopmop.checks.javascript.types import JavaScriptTypesCheck

    registry.register(JavaScriptLintFormatCheck)
    registry.register(JavaScriptTestsCheck)
    registry.register(JavaScriptCoverageCheck)
    registry.register(FrontendCheck)
    registry.register(JavaScriptTypesCheck)


def _register_crosscutting_checks(registry: CheckRegistry) -> None:
    """Register security, quality, and general checks."""
    from slopmop.checks.general.jinja2_templates import TemplateValidationCheck
    from slopmop.checks.pr.comments import PRCommentsCheck
    from slopmop.checks.quality import (
        BogusTestsCheck,
        ComplexityCheck,
        DeadCodeCheck,
        LocLockCheck,
        SourceDuplicationCheck,
        StringDuplicationCheck,
    )
    from slopmop.checks.security import SecurityCheck, SecurityLocalCheck

    registry.register(SecurityCheck)
    registry.register(SecurityLocalCheck)
    registry.register(BogusTestsCheck)
    registry.register(ComplexityCheck)
    registry.register(DeadCodeCheck)
    registry.register(SourceDuplicationCheck)
    registry.register(StringDuplicationCheck)
    registry.register(LocLockCheck)
    registry.register(TemplateValidationCheck)
    registry.register(PRCommentsCheck)


def _register_aliases(registry: CheckRegistry) -> None:
    """Register all profile aliases."""
    registry.register_alias(
        "commit",
        [
            "python:lint-format",
            "python:static-analysis",
            "python:type-checking",
            "python:tests",
            "python:coverage",
            "quality:complexity",
            "quality:dead-code",
            "quality:source-duplication",
            "quality:string-duplication",
            "quality:bogus-tests",
            "quality:loc-lock",
            "security:local",
            "javascript:lint-format",
            "javascript:tests",
            "javascript:coverage",
        ],
    )

    registry.register_alias(
        "pr",
        [
            "pr:comments",
            "python:lint-format",
            "python:static-analysis",
            "python:type-checking",
            "python:tests",
            "python:coverage",
            "python:diff-coverage",
            "python:new-code-coverage",
            "quality:complexity",
            "quality:dead-code",
            "quality:source-duplication",
            "quality:string-duplication",
            "quality:bogus-tests",
            "quality:loc-lock",
            "security:full",
            "javascript:lint-format",
            "javascript:tests",
            "javascript:coverage",
        ],
    )

    registry.register_alias("quick", ["python:lint-format", "security:local"])

    registry.register_alias(
        "python",
        [
            "python:lint-format",
            "python:static-analysis",
            "python:type-checking",
            "python:tests",
            "python:coverage",
        ],
    )

    registry.register_alias(
        "javascript",
        [
            "javascript:lint-format",
            "javascript:types",
            "javascript:tests",
            "javascript:coverage",
            "javascript:frontend",
        ],
    )

    registry.register_alias("security", ["security:full"])
    registry.register_alias("security-local", ["security:local"])

    registry.register_alias(
        "quality",
        [
            "quality:complexity",
            "quality:source-duplication",
            "quality:string-duplication",
            "quality:bogus-tests",
            "quality:loc-lock",
        ],
    )

    registry.register_alias(
        "e2e",
        [
            "integration:smoke-tests",
            "integration:integration-tests",
            "integration:e2e-tests",
        ],
    )


def register_all_checks() -> None:
    """Register all available checks and aliases with the registry.

    Call this function before running checks to ensure all checks are available.
    """
    registry = get_registry()
    _register_python_checks(registry)
    _register_javascript_checks(registry)
    _register_crosscutting_checks(registry)
    _register_aliases(registry)


_checks_registered = False


def ensure_checks_registered() -> None:
    """Ensure all checks are registered (idempotent).

    This is safe to call multiple times - checks will only be registered once.
    Checks the registry state, not just a flag, to handle test scenarios where
    the registry might have been reset.
    """
    global _checks_registered
    registry = get_registry()
    # Also check if registry is actually populated, not just the flag
    # This handles test scenarios where registry was reset
    if not _checks_registered or len(registry._check_classes) == 0:
        register_all_checks()
        _checks_registered = True
