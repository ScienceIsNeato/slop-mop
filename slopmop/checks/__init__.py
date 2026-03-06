"""Quality gate checks for slopmop.

This module provides registration for all available checks and aliases.

The ``slopmop.core.registry`` import is deferred to function-call time.
``registry.py`` imports ``slopmop.checks.base``, which must run this
``__init__.py`` first (parent package initialisation).  If we import
registry here at module level, the cycle only happens to work when
``sm.py`` is the entry point because it touches ``checks.base`` before
``registry`` does.  A bare ``from slopmop.core.registry import
get_registry`` in a REPL blows up with a partial-initialisation
ImportError.  Deferring to function bodies breaks the cycle in every
import order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slopmop.core.registry import CheckRegistry


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
    from slopmop.checks.general.jinja2_templates import TemplateValidationCheck
    from slopmop.checks.pr.comments import PRCommentsCheck
    from slopmop.checks.quality import (
        BogusTestsCheck,
        ComplexityCheck,
        ConfigDebtCheck,
        DeadCodeCheck,
        DebuggerArtifactsCheck,
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
    registry.register(DebuggerArtifactsCheck)
    registry.register(GateDodgingCheck)
    registry.register(SourceDuplicationCheck)
    registry.register(StringDuplicationCheck)
    registry.register(LocLockCheck)
    registry.register(ConfigDebtCheck)
    registry.register(TemplateValidationCheck)
    registry.register(PRCommentsCheck)


def _register_aliases(registry: CheckRegistry) -> None:
    """Register convenience group aliases for -g flag.

    Gate level (swab/scour) is intrinsic to each check class via the
    ``level`` ClassVar.  Aliases here are convenience shortcuts for
    ``-g`` when you want to run a subset of gates by topic.
    """
    # ── Convenience group aliases (for -g flag) ───────────────────────
    registry.register_alias(
        "quick", ["laziness:sloppy-formatting.py", "myopia:vulnerability-blindness.py"]
    )

    registry.register_alias(
        "python",
        [
            "laziness:sloppy-formatting.py",
            "overconfidence:missing-annotations.py",
            "overconfidence:type-blindness.py",
            "overconfidence:untested-code.py",
            "overconfidence:coverage-gaps.py",
        ],
    )

    registry.register_alias(
        "javascript",
        [
            "laziness:sloppy-formatting.js",
            "overconfidence:type-blindness.js",
            "overconfidence:untested-code.js",
            "overconfidence:coverage-gaps.js",
            "laziness:sloppy-frontend.js",
        ],
    )

    registry.register_alias("security", ["myopia:dependency-risk.py"])
    registry.register_alias("security-local", ["myopia:vulnerability-blindness.py"])

    registry.register_alias(
        "quality",
        [
            "laziness:complexity-creep.py",
            "myopia:source-duplication",
            "myopia:string-duplication.py",
            "deceptiveness:bogus-tests.py",
            "myopia:code-sprawl",
        ],
    )


def register_all_checks() -> None:
    """Register all available checks and aliases with the registry.

    Call this function before running checks to ensure all checks are available.
    """
    from slopmop.core.registry import get_registry

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
    from slopmop.core.registry import get_registry

    registry = get_registry()
    # Also check if registry is actually populated, not just the flag
    # This handles test scenarios where registry was reset
    if not _checks_registered or len(registry._check_classes) == 0:
        register_all_checks()
        _checks_registered = True
