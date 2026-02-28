"""Quality gate checks for slopmop.

This module provides registration for all available checks and aliases.
"""

from slopmop.core.registry import CheckRegistry, get_registry


def _register_python_checks(registry: CheckRegistry) -> None:
    """Register all Python-related checks."""
    from slopmop.checks.python.coverage import (
        PythonCoverageCheck,
        PythonDiffCoverageCheck,
    )
    from slopmop.checks.python.lint_format import PythonLintFormatCheck
    from slopmop.checks.python.static_analysis import PythonStaticAnalysisCheck
    from slopmop.checks.python.tests import PythonTestsCheck
    from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

    registry.register(PythonLintFormatCheck)
    registry.register(PythonTestsCheck)
    registry.register(PythonCoverageCheck)
    registry.register(PythonDiffCoverageCheck)
    registry.register(PythonStaticAnalysisCheck)
    registry.register(PythonTypeCheckingCheck)


def _register_javascript_checks(registry: CheckRegistry) -> None:
    """Register all JavaScript-related checks."""
    from slopmop.checks.javascript.bogus_tests import JavaScriptBogusTestsCheck
    from slopmop.checks.javascript.coverage import JavaScriptCoverageCheck
    from slopmop.checks.javascript.eslint_expect import JavaScriptExpectCheck
    from slopmop.checks.javascript.eslint_quick import FrontendCheck
    from slopmop.checks.javascript.lint_format import JavaScriptLintFormatCheck
    from slopmop.checks.javascript.tests import JavaScriptTestsCheck
    from slopmop.checks.javascript.types import JavaScriptTypesCheck

    registry.register(JavaScriptLintFormatCheck)
    registry.register(JavaScriptTestsCheck)
    registry.register(JavaScriptCoverageCheck)
    registry.register(FrontendCheck)
    registry.register(JavaScriptTypesCheck)
    registry.register(JavaScriptBogusTestsCheck)
    registry.register(JavaScriptExpectCheck)


def _register_crosscutting_checks(registry: CheckRegistry) -> None:
    """Register security, quality, and general checks."""
    from slopmop.checks.general.deploy_tests import DeployScriptTestsCheck
    from slopmop.checks.general.jinja2_templates import TemplateValidationCheck
    from slopmop.checks.pr.comments import PRCommentsCheck
    from slopmop.checks.quality import (
        BogusTestsCheck,
        ComplexityCheck,
        DeadCodeCheck,
        GateDodgingCheck,
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
    registry.register(GateDodgingCheck)
    registry.register(SourceDuplicationCheck)
    registry.register(StringDuplicationCheck)
    registry.register(LocLockCheck)
    registry.register(TemplateValidationCheck)
    registry.register(DeployScriptTestsCheck)
    registry.register(PRCommentsCheck)


def _register_legacy_aliases(registry: CheckRegistry) -> None:
    """Register legacy ``commit`` and ``pr`` profile aliases.

    Kept for backward compatibility with ``sm validate commit`` /
    ``sm validate pr`` (deprecated shim).  Gate level (swab/scour) is now
    intrinsic to each check class via the ``level`` ClassVar.
    """
    registry.register_alias(
        "commit",
        [
            "laziness:py-lint",
            "overconfidence:py-static-analysis",
            "overconfidence:py-types",
            "overconfidence:py-tests",
            "deceptiveness:py-coverage",
            "laziness:complexity",
            "laziness:dead-code",
            "myopia:source-duplication",
            "myopia:string-duplication",
            "deceptiveness:bogus-tests",
            "deceptiveness:gate-dodging",
            "myopia:loc-lock",
            "myopia:security-scan",
            "laziness:js-lint",
            "overconfidence:js-types",
            "overconfidence:js-tests",
            "deceptiveness:js-coverage",
            "deceptiveness:js-bogus-tests",
            "deceptiveness:js-expect-assert",
        ],
    )

    registry.register_alias(
        "pr",
        [
            "pr:comments",
            "laziness:py-lint",
            "overconfidence:py-static-analysis",
            "overconfidence:py-types",
            "overconfidence:py-tests",
            "deceptiveness:py-coverage",
            "deceptiveness:py-diff-coverage",
            "laziness:complexity",
            "laziness:dead-code",
            "myopia:source-duplication",
            "myopia:string-duplication",
            "deceptiveness:bogus-tests",
            "deceptiveness:gate-dodging",
            "myopia:loc-lock",
            "myopia:security-audit",
            "laziness:js-lint",
            "overconfidence:js-types",
            "overconfidence:js-tests",
            "deceptiveness:js-coverage",
            "deceptiveness:js-bogus-tests",
            "deceptiveness:js-expect-assert",
        ],
    )


def _register_aliases(registry: CheckRegistry) -> None:
    """Register convenience group aliases for -g flag.

    These are NOT profiles — gate level (swab/scour) is intrinsic to each
    check class via the ``level`` ClassVar.  Aliases here are convenience
    shortcuts for ``-g`` when you want to run a subset of gates by topic.
    """
    # Legacy profile aliases (backward compat for sm validate)
    _register_legacy_aliases(registry)

    # ── Convenience group aliases (for -g flag) ───────────────────────
    registry.register_alias("quick", ["laziness:py-lint", "myopia:security-scan"])

    registry.register_alias(
        "python",
        [
            "laziness:py-lint",
            "overconfidence:py-static-analysis",
            "overconfidence:py-types",
            "overconfidence:py-tests",
            "deceptiveness:py-coverage",
        ],
    )

    registry.register_alias(
        "javascript",
        [
            "laziness:js-lint",
            "overconfidence:js-types",
            "overconfidence:js-tests",
            "deceptiveness:js-coverage",
            "laziness:js-frontend",
        ],
    )

    registry.register_alias("security", ["myopia:security-audit"])
    registry.register_alias("security-local", ["myopia:security-scan"])

    registry.register_alias(
        "quality",
        [
            "laziness:complexity",
            "myopia:source-duplication",
            "myopia:string-duplication",
            "deceptiveness:bogus-tests",
            "myopia:loc-lock",
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
