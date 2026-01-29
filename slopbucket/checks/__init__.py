"""Quality gate checks for slopbucket.

This module provides registration for all available checks and aliases.
"""

from slopbucket.core.registry import get_registry


def register_all_checks() -> None:
    """Register all available checks and aliases with the registry.

    Call this function before running checks to ensure all checks are available.
    """
    registry = get_registry()

    # Import and register Python checks
    from slopbucket.checks.python.coverage import (
        PythonCoverageCheck,
        PythonDiffCoverageCheck,
        PythonNewCodeCoverageCheck,
    )
    from slopbucket.checks.python.lint_format import PythonLintFormatCheck
    from slopbucket.checks.python.static_analysis import PythonStaticAnalysisCheck
    from slopbucket.checks.python.test_types import (
        E2ETestCheck,
        IntegrationTestCheck,
        SmokeTestCheck,
    )
    from slopbucket.checks.python.tests import PythonTestsCheck

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
    from slopbucket.checks.javascript.coverage import JavaScriptCoverageCheck
    from slopbucket.checks.javascript.eslint_quick import FrontendCheck
    from slopbucket.checks.javascript.lint_format import JavaScriptLintFormatCheck
    from slopbucket.checks.javascript.tests import JavaScriptTestsCheck

    registry.register(JavaScriptLintFormatCheck)
    registry.register(JavaScriptTestsCheck)
    registry.register(JavaScriptCoverageCheck)
    registry.register(FrontendCheck)

    # Import and register security checks (cross-cutting)
    from slopbucket.checks.security import SecurityCheck, SecurityLocalCheck

    registry.register(SecurityCheck)
    registry.register(SecurityLocalCheck)

    # Import and register quality checks (cross-cutting)
    from slopbucket.checks.quality import ComplexityCheck, DuplicationCheck

    registry.register(ComplexityCheck)
    registry.register(DuplicationCheck)

    # Import and register general checks
    from slopbucket.checks.general.jinja2_templates import TemplateValidationCheck

    registry.register(TemplateValidationCheck)

    # Import and register PR checks
    from slopbucket.checks.pr.comments import PRCommentsCheck

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
