"""Check registry for discovering and managing quality gate checks.

The registry maintains a catalog of available checks, enabling dynamic
check discovery and configuration-based selection.
"""

import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple, Type

from slopmop.checks.base import BaseCheck, GateLevel, RemediationChurn
from slopmop.checks.metadata import builtin_reasoning_for_check_class
from slopmop.core.result import CheckDefinition

logger = logging.getLogger(__name__)


# Built-in remediation order.
# Lower positions are fixed first. This list is the single source of truth for
# intentional built-in ordering; anything omitted falls back to explicit
# per-check priority, then to the churn-band defaults below.
#
# Ordering principle:
# 1. Remove high-risk/security hazards first.
# 2. Fix structural churn before proving correctness on shifting sand.
# 3. Repair deceptive tests before trusting test-derived signals.
# 4. Re-establish correctness proofs (types/tests/coverage).
# 5. Leave polish and low-churn cleanup for the end.
@lru_cache(maxsize=1)
def curated_remediation_order_classes() -> Tuple[Type[BaseCheck], ...]:
    """Return the curated remediation order keyed by check classes."""
    from slopmop.checks.dart import (
        DartBogusTestsCheck,
        DartCoverageCheck,
        DartFormatCheck,
        DartGeneratedArtifactsCheck,
        FlutterAnalyzeCheck,
        FlutterTestsCheck,
    )
    from slopmop.checks.general.jinja2_templates import TemplateValidationCheck
    from slopmop.checks.javascript.bogus_tests import JavaScriptBogusTestsCheck
    from slopmop.checks.javascript.coverage import JavaScriptCoverageCheck
    from slopmop.checks.javascript.eslint_expect import JavaScriptExpectCheck
    from slopmop.checks.javascript.eslint_quick import FrontendCheck
    from slopmop.checks.javascript.lint_format import JavaScriptLintFormatCheck
    from slopmop.checks.javascript.tests import JavaScriptTestsCheck
    from slopmop.checks.javascript.types import JavaScriptTypesCheck
    from slopmop.checks.pr.comments import PRCommentsCheck
    from slopmop.checks.python.coverage import (
        PythonCoverageCheck,
        PythonDiffCoverageCheck,
    )
    from slopmop.checks.python.lint_format import PythonLintFormatCheck
    from slopmop.checks.python.static_analysis import PythonStaticAnalysisCheck
    from slopmop.checks.python.tests import PythonTestsCheck
    from slopmop.checks.python.type_checking import PythonTypeCheckingCheck
    from slopmop.checks.quality import (
        AmbiguityMinesCheck,
        BogusTestsCheck,
        ComplexityCheck,
        ConfigDebtCheck,
        DeadCodeCheck,
        DebuggerArtifactsCheck,
        GateDodgingCheck,
        LocLockCheck,
        RepeatedCodeCheck,
        StringDuplicationCheck,
    )
    from slopmop.checks.security import SecurityCheck, SecurityLocalCheck

    return (
        SecurityCheck,
        SecurityLocalCheck,
        RepeatedCodeCheck,
        AmbiguityMinesCheck,
        DeadCodeCheck,
        StringDuplicationCheck,
        GateDodgingCheck,
        BogusTestsCheck,
        JavaScriptBogusTestsCheck,
        DartBogusTestsCheck,
        JavaScriptExpectCheck,
        PythonStaticAnalysisCheck,
        FlutterAnalyzeCheck,
        PythonTypeCheckingCheck,
        JavaScriptTypesCheck,
        LocLockCheck,
        ComplexityCheck,
        PythonTestsCheck,
        JavaScriptTestsCheck,
        FlutterTestsCheck,
        PythonCoverageCheck,
        JavaScriptCoverageCheck,
        DartCoverageCheck,
        PythonDiffCoverageCheck,
        ConfigDebtCheck,
        PRCommentsCheck,
        FrontendCheck,
        TemplateValidationCheck,
        PythonLintFormatCheck,
        JavaScriptLintFormatCheck,
        DartFormatCheck,
        DartGeneratedArtifactsCheck,
        DebuggerArtifactsCheck,
    )


@lru_cache(maxsize=1)
def curated_remediation_order_names() -> Tuple[str, ...]:
    """Return curated remediation gate names derived from the class order."""
    return tuple(
        check_class({}).full_name for check_class in curated_remediation_order_classes()
    )


@lru_cache(maxsize=1)
def _curated_remediation_priority() -> Dict[Type[BaseCheck], int]:
    return {
        check_class: (index + 1) * 10
        for index, check_class in enumerate(curated_remediation_order_classes())
    }


_DEFAULT_REMEDIATION_PRIORITY_BY_CHURN: Dict[RemediationChurn, int] = {
    RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY: 100,
    RemediationChurn.DOWNSTREAM_CHANGES_LIKELY: 200,
    RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY: 300,
    RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY: 400,
}


class CheckRegistry:
    """Registry for quality gate checks.

    The registry provides:
    - Registration of check classes
    - Check discovery and instantiation
    - Configuration-based filtering
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._check_classes: Dict[str, Type[BaseCheck]] = {}
        self._definitions: Dict[str, CheckDefinition] = {}

    def register(
        self,
        check_class: Type[BaseCheck],
        definition: Optional[CheckDefinition] = None,
    ) -> None:
        """Register a check class.

        Args:
            check_class: The check class to register
            definition: Optional check definition with metadata
        """
        # Create temporary instance to get name
        temp_instance = check_class({})
        # Use full_name (category:name) for unique registration
        name = temp_instance.full_name

        # Re-registration is expected (idempotent), no warning needed
        self._check_classes[name] = check_class

        if getattr(check_class, "REASONING", None) is None:
            reasoning = builtin_reasoning_for_check_class(check_class)
            if reasoning is not None:
                check_class.REASONING = reasoning

        # Create definition if not provided
        if definition is None:
            definition = CheckDefinition(
                flag=name,
                name=temp_instance.display_name,
                depends_on=temp_instance.depends_on,
                auto_fix=temp_instance.can_auto_fix(),
            )
        self._definitions[name] = definition

        logger.debug(f"Registered check: {name}")

    def get_check(self, name: str, config: Dict[str, Any]) -> Optional[BaseCheck]:
        """Get a single check instance by name.

        Args:
            name: Check name (format: 'category:check-name')
            config: Full configuration dictionary

        Returns:
            Check instance or None if not found
        """
        check_class = self._check_classes.get(name)
        if check_class is None:
            return None

        # Extract gate-specific config from full config
        # Config structure: { "category": { "gates": { "check-name": {...} } } }
        gate_config = self._extract_gate_config(name, config)
        return check_class(gate_config)

    def _extract_gate_config(
        self, name: str, full_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract gate-specific config from full config.

        Args:
            name: Check name in format 'category:check-name'
            full_config: Full configuration dictionary

        Returns:
            Configuration dictionary for the specific gate
        """
        if ":" not in name:
            return {}

        category, gate_name = name.split(":", 1)

        # Get category config (e.g., python, javascript, security)
        cat_config = full_config.get(category, {})

        # Get gates config
        gates = cat_config.get("gates", {})

        # Get specific gate config
        gate_config = gates.get(gate_name, {}).copy()

        return gate_config

    def get_checks(self, names: List[str], config: Dict[str, Any]) -> List[BaseCheck]:
        """Get check instances by name.

        Args:
            names: List of check names
            config: Configuration dictionary

        Returns:
            List of check instances
        """
        # Remove duplicates while preserving order
        seen: set[str] = set()
        unique_names: List[str] = []
        for name in names:
            if name not in seen:
                seen.add(name)
                unique_names.append(name)

        # Create check instances
        checks: List[BaseCheck] = []
        for name in unique_names:
            check = self.get_check(name, config)
            if check is not None:
                checks.append(check)
            else:
                logger.warning(f"Unknown check: {name}")

        return checks

    def get_definition(self, name: str) -> Optional[CheckDefinition]:
        """Get the definition for a check.

        Args:
            name: Check name

        Returns:
            CheckDefinition or None if not found
        """
        return self._definitions.get(name)

    def list_checks(self) -> List[str]:
        """List all registered check names."""
        return list(self._check_classes.keys())

    @staticmethod
    def _resolved_level(
        check_class: Type[BaseCheck],
        gate_config: Optional[Dict[str, Any]] = None,
    ) -> GateLevel:
        """Return the effective run level after applying config overrides."""
        run_on = (gate_config or {}).get("run_on")
        if isinstance(run_on, str):
            try:
                return GateLevel(run_on)
            except ValueError:
                pass
        return check_class.level

    def get_gate_names_for_level(
        self,
        level: GateLevel,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Get all registered gate names appropriate for a given level.

        Swab returns only SWAB-level gates.
        Scour returns ALL gates (SWAB + SCOUR) since scour is a superset.

        Args:
            level: The gate level to filter by

        Returns:
            List of gate names (category:check-name format)
        """
        names: List[str] = []
        for name, check_class in self._check_classes.items():
            gate_config = self._extract_gate_config(name, config or {})
            resolved_level = self._resolved_level(check_class, gate_config)
            if level == GateLevel.SCOUR or resolved_level == GateLevel.SWAB:
                names.append(name)
        return names

    def get_applicable_checks(
        self, project_root: str, config: Dict[str, Any]
    ) -> List[BaseCheck]:
        """Get all checks that are applicable to a project.

        Args:
            project_root: Path to project root
            config: Configuration dictionary

        Returns:
            List of applicable check instances
        """
        applicable: List[BaseCheck] = []
        for name, check_class in self._check_classes.items():
            check = check_class(config)
            if check.is_applicable(project_root):
                applicable.append(check)
        return applicable

    def remediation_priority_for_check(self, check: BaseCheck) -> int:
        """Return the fine-grained remediation priority for a check.

        Explicit ``check.remediation_priority`` wins. Otherwise we derive a
        default band from ``check.remediation_churn`` with intentional gaps so
        new explicit priorities can be inserted cleanly.
        """
        curated = _curated_remediation_priority().get(type(check))
        if curated is not None:
            return curated
        explicit = getattr(check, "remediation_priority", None)
        if explicit is not None:
            return int(explicit)
        return _DEFAULT_REMEDIATION_PRIORITY_BY_CHURN[check.remediation_churn]

    def remediation_priority_source_for_check(self, check: BaseCheck) -> str:
        """Return where a check's remediation priority came from."""
        if type(check) in _curated_remediation_priority():
            return "curated"
        if getattr(check, "remediation_priority", None) is not None:
            return "explicit"
        return "churn-default"

    def remediation_sort_key(self, check: BaseCheck) -> Tuple[int, int, str]:
        """Return the canonical remediation ordering key for a check."""
        return (
            1 if getattr(check, "terminal", False) else 0,
            self.remediation_priority_for_check(check),
            check.full_name,
        )

    def remediation_sort_key_for_name(
        self, name: str
    ) -> Optional[Tuple[int, int, str]]:
        """Return remediation ordering for a registered gate name.

        Unknown names return ``None`` so callers can preserve original order for
        non-gate rows instead of inventing a fake priority.
        """
        check_class = self._check_classes.get(name)
        if check_class is None:
            return None
        return self.remediation_sort_key(check_class({}))

    def sort_checks_for_remediation(self, checks: List[BaseCheck]) -> List[BaseCheck]:
        """Sort instantiated checks in canonical remediation order."""
        return sorted(checks, key=self.remediation_sort_key)


# Default registry instance
_default_registry: Optional[CheckRegistry] = None


def get_registry() -> CheckRegistry:
    """Get the default check registry singleton."""
    global _default_registry
    if _default_registry is None:
        _default_registry = CheckRegistry()
    return _default_registry


def register_check(check_class: Type[BaseCheck]) -> Type[BaseCheck]:
    """Decorator to register a check class with the default registry.

    Usage:
        @register_check
        class MyCheck(BaseCheck):
            ...
    """
    get_registry().register(check_class)
    return check_class
