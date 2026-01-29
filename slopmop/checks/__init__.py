"""Quality gate checks for slopmop.

This module provides registration for all available checks and aliases.
"""

from slopmop.core.registry import get_registry


def register_all_checks() -> None:
    """Register all available checks and aliases with the registry.

    Call this function before running checks to ensure all checks are available.
    """
    registry = get_registry()

    # Import and register Python checks
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

    registry.register(PythonLintFormatCheck)
    registry.register(PythonTestsCheck)
    registry.register(PythonCoverageCheck)
    registry.register(PythonDiffCoverageCheck)
    registry.register(PythonNewCodeCoverageCheck)
    registry.register(PythonStaticAnalysisCheck)
    registry.register(SmokeTestCheck)
    registry.register(IntegrationTestCheck)
    registry.register(E2ETestCheck)

    # Import and register JavaScript checks
    from slopmop.checks.javascript.coverage import JavaScriptCoverageCheck
    from slopmop.checks.javascript.eslint_quick import FrontendCheck
    from slopmop.checks.javascript.lint_format import JavaScriptLintFormatCheck
    from slopmop.checks.javascript.tests import JavaScriptTestsCheck

    registry.register(JavaScriptLintFormatCheck)
    registry.register(JavaScriptTestsCheck)
    registry.register(JavaScriptCoverageCheck)
    registry.register(FrontendCheck)

    # Import and register security checks (cross-cutting)
    from slopmop.checks.security import SecurityCheck, SecurityLocalCheck

    registry.register(SecurityCheck)
    registry.register(SecurityLocalCheck)

    # Import and register quality checks (cross-cutting)
    from slopmop.checks.quality import ComplexityCheck, DuplicationCheck

    registry.register(ComplexityCheck)
    registry.register(DuplicationCheck)

    # Import and register general checks
    from slopmop.checks.general.jinja2_templates import TemplateValidationCheck

    registry.register(TemplateValidationCheck)

    # Import and register PR checks
    from slopmop.checks.pr.comments import PRCommentsCheck

    registry.register(PRCommentsCheck)

    # Register aliases
    registry.register_alias(
        "commit",
        [
            "python:lint-format",
            "python:static-analysis",
            "python:tests",
            "python:coverage",
            "quality:complexity",
            "security:local",
        ],
    )

    registry.register_alias(
        "pr",
        [
            "pr:comments",
            "python:lint-format",
            "python:static-analysis",
            "python:tests",
            "python:coverage",
            "python:diff-coverage",
            "python:new-code-coverage",
            "quality:complexity",
            "security:full",
            "quality:duplication",
            "javascript:lint-format",
            "javascript:tests",
            "javascript:coverage",
        ],
    )

    registry.register_alias(
        "quick",
        [
            "python:lint-format",
            "security:local",
        ],
    )

    registry.register_alias(
        "python",
        [
            "python:lint-format",
            "python:static-analysis",
            "python:tests",
            "python:coverage",
        ],
    )

    registry.register_alias(
        "javascript",
        [
            "javascript:lint-format",
            "javascript:tests",
            "javascript:coverage",
            "javascript:frontend",
        ],
    )

    registry.register_alias(
        "security",
        [
            "security:full",
        ],
    )

    registry.register_alias(
        "security-local",
        [
            "security:local",
        ],
    )

    registry.register_alias(
        "quality",
        [
            "quality:complexity",
            "quality:duplication",
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
