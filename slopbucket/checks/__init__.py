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
    from slopbucket.checks.python.coverage import PythonCoverageCheck
    from slopbucket.checks.python.lint_format import PythonLintFormatCheck
    from slopbucket.checks.python.static_analysis import PythonStaticAnalysisCheck
    from slopbucket.checks.python.tests import PythonTestsCheck

    registry.register(PythonLintFormatCheck)
    registry.register(PythonTestsCheck)
    registry.register(PythonCoverageCheck)
    registry.register(PythonStaticAnalysisCheck)

    # Import and register JavaScript checks
    from slopbucket.checks.javascript.lint_format import JavaScriptLintFormatCheck
    from slopbucket.checks.javascript.tests import JavaScriptTestsCheck

    registry.register(JavaScriptLintFormatCheck)
    registry.register(JavaScriptTestsCheck)

    # Register aliases
    registry.register_alias(
        "commit",
        [
            "python-lint-format",
            "python-static-analysis",
            "python-tests",
            "python-coverage",
        ],
    )

    registry.register_alias(
        "pr",
        [
            "python-lint-format",
            "python-static-analysis",
            "python-tests",
            "python-coverage",
            "js-lint-format",
            "js-tests",
        ],
    )

    registry.register_alias(
        "quick",
        [
            "python-lint-format",
        ],
    )

    registry.register_alias(
        "python",
        [
            "python-lint-format",
            "python-static-analysis",
            "python-tests",
            "python-coverage",
        ],
    )

    registry.register_alias(
        "javascript",
        [
            "js-lint-format",
            "js-tests",
        ],
    )
