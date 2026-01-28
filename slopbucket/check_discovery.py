"""
Check discovery — dynamic loading of check classes from the registry.

Resolves CheckDef → concrete BaseCheck subclass instances.
Provides validation that loaded classes conform to the interface.
"""

import importlib
import logging
from typing import Dict, List

from slopbucket.base_check import BaseCheck
from slopbucket.config import CheckDef

logger = logging.getLogger(__name__)


class DiscoveryError(Exception):
    """Raised when a check module cannot be loaded or validated."""

    pass


def load_check(check_def: CheckDef) -> BaseCheck:
    """Load a single check class from a CheckDef.

    Args:
        check_def: Definition containing module path and class name.

    Returns:
        Instantiated BaseCheck subclass.

    Raises:
        DiscoveryError: If module or class cannot be loaded.
    """
    try:
        module = importlib.import_module(check_def.module_path)
    except ImportError as e:
        raise DiscoveryError(
            f"Cannot import check module '{check_def.module_path}': {e}"
        ) from e

    if not hasattr(module, check_def.class_name):
        raise DiscoveryError(
            f"Module '{check_def.module_path}' has no class '{check_def.class_name}'"
        )

    cls = getattr(module, check_def.class_name)

    if not issubclass(cls, BaseCheck):
        raise DiscoveryError(
            f"Class '{check_def.class_name}' does not subclass BaseCheck"
        )

    instance = cls()

    # Validate interface compliance
    if instance.name != check_def.name:
        logger.warning(
            "Check class name mismatch: CheckDef.name='%s' but class.name='%s'",
            check_def.name,
            instance.name,
        )

    return instance


def load_checks(check_defs: List[CheckDef]) -> List[BaseCheck]:
    """Load multiple check classes, collecting errors.

    Args:
        check_defs: List of check definitions to load.

    Returns:
        List of instantiated check objects (in order).

    Raises:
        DiscoveryError: If any check fails to load.
    """
    checks: List[BaseCheck] = []
    errors: List[str] = []

    for check_def in check_defs:
        try:
            check = load_check(check_def)
            checks.append(check)
        except DiscoveryError as e:
            errors.append(str(e))

    if errors:
        error_summary = "\n  ".join(errors)
        raise DiscoveryError(
            f"Failed to load {len(errors)} check(s):\n  {error_summary}"
        )

    return checks


def validate_all_registered() -> Dict[str, str]:
    """Attempt to load every check in the registry.

    Returns:
        Dict mapping check names to error messages (empty if all load successfully).
    """
    from slopbucket.config import CHECK_REGISTRY

    errors: Dict[str, str] = {}
    for name, check_def in CHECK_REGISTRY.items():
        try:
            load_check(check_def)
        except DiscoveryError as e:
            errors[name] = str(e)

    return errors
