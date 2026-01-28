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
    from slopbucket.checks.python.complexity import PythonComplexityCheck
    from slopbucket.checks.python.coverage import (
        PythonCoverageCheck,
        PythonDiffCoverageCheck,
        PythonNewCodeCoverageCheck,
    )
    from slopbucket.checks.python.lint_format import PythonLintFormatCheck
    from slopbucket.checks.python.security import (
        PythonSecurityCheck,
        PythonSecurityLocalCheck,
    )
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
    registry.register(PythonComplexityCheck)
    registry.register(PythonSecurityCheck)
    registry.register(PythonSecurityLocalCheck)
    registry.register(SmokeTestCheck)
    registry.register(IntegrationTestCheck)
    registry.register(E2ETestCheck)

    # Import and register JavaScript checks
    from slopbucket.checks.javascript.coverage import JavaScriptCoverageCheck
    from slopbucket.checks.javascript.frontend import FrontendCheck
    from slopbucket.checks.javascript.lint_format import JavaScriptLintFormatCheck
    from slopbucket.checks.javascript.tests import JavaScriptTestsCheck

    registry.register(JavaScriptLintFormatCheck)
    registry.register(JavaScriptTestsCheck)
    registry.register(JavaScriptCoverageCheck)
    registry.register(FrontendCheck)

    # Import and register general checks
    from slopbucket.checks.general.duplication import DuplicationCheck
    from slopbucket.checks.general.templates import TemplateValidationCheck

    registry.register(DuplicationCheck)
    registry.register(TemplateValidationCheck)

    # Register aliases
    registry.register_alias(
        "commit",
        [
            "python-lint-format",
            "python-static-analysis",
            "python-tests",
            "python-coverage",
            "python-complexity",
            "python-security-local",
        ],
    )

    registry.register_alias(
        "pr",
        [
            "python-lint-format",
            "python-static-analysis",
            "python-tests",
            "python-coverage",
            "python-diff-coverage",
            "python-new-code-coverage",
            "python-complexity",
            "python-security",
            "duplication",
            "js-lint-format",
            "js-tests",
            "js-coverage",
        ],
    )

    registry.register_alias(
        "quick",
        [
            "python-lint-format",
            "python-security-local",
        ],
    )

    registry.register_alias(
        "python",
        [
            "python-lint-format",
            "python-static-analysis",
            "python-tests",
            "python-coverage",
            "python-complexity",
            "python-security",
        ],
    )

    registry.register_alias(
        "javascript",
        [
            "js-lint-format",
            "js-tests",
            "js-coverage",
            "frontend-check",
        ],
    )

    registry.register_alias(
        "security",
        [
            "python-security",
        ],
    )

    registry.register_alias(
        "security-local",
        [
            "python-security-local",
        ],
    )

    registry.register_alias(
        "e2e",
        [
            "smoke-tests",
            "integration-tests",
            "e2e-tests",
        ],
    )
