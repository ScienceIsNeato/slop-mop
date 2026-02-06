"""Check registry for discovering and managing quality gate checks.

The registry maintains a catalog of available checks and aliases,
enabling dynamic check discovery and configuration-based selection.
"""

import logging
from typing import Any, Dict, List, Optional, Type

from slopmop.checks.base import BaseCheck
from slopmop.core.result import CheckDefinition

logger = logging.getLogger(__name__)


class CheckRegistry:
    """Registry for quality gate checks.

    The registry provides:
    - Registration of check classes
    - Alias definitions for check groups
    - Check discovery and instantiation
    - Configuration-based filtering
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._check_classes: Dict[str, Type[BaseCheck]] = {}
        self._aliases: Dict[str, List[str]] = {}
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

    def register_alias(self, alias: str, check_names: List[str]) -> None:
        """Register a check alias (group of checks).

        Args:
            alias: Name of the alias
            check_names: List of check names included in this alias
        """
        self._aliases[alias] = check_names
        logger.debug(f"Registered alias '{alias}': {check_names}")

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
        return gates.get(gate_name, {})

    def get_checks(self, names: List[str], config: Dict[str, Any]) -> List[BaseCheck]:
        """Get check instances by name, expanding aliases.

        Args:
            names: List of check names or aliases
            config: Configuration dictionary

        Returns:
            List of check instances
        """
        # Expand aliases to individual check names
        expanded_names: List[str] = []
        for name in names:
            if name in self._aliases:
                expanded_names.extend(self._aliases[name])
            else:
                expanded_names.append(name)

        # Remove duplicates while preserving order
        seen = set()
        unique_names = []
        for name in expanded_names:
            if name not in seen:
                seen.add(name)
                unique_names.append(name)

        # Create check instances
        checks = []
        for name in unique_names:
            check = self.get_check(name, config)
            if check is not None:
                checks.append(check)
            else:
                logger.warning(f"Unknown check: {name}")

        return checks

    def expand_alias(self, alias: str) -> List[str]:
        """Expand an alias to its constituent check names.

        Args:
            alias: Alias name

        Returns:
            List of check names, or [alias] if not an alias
        """
        return self._aliases.get(alias, [alias])

    def is_alias(self, name: str) -> bool:
        """Check if a name is a registered alias."""
        return name in self._aliases

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

    def list_aliases(self) -> Dict[str, List[str]]:
        """List all registered aliases and their checks."""
        return dict(self._aliases)

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
        applicable = []
        for name, check_class in self._check_classes.items():
            check = check_class(config)
            if check.is_applicable(project_root):
                applicable.append(check)
        return applicable


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
