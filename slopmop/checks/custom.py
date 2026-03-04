"""User-defined custom gates via .sb_config.json.

Custom gates let users define repo-specific checks as shell commands
without writing Python BaseCheck subclasses.  They run alongside built-in
gates and respect the same enable/disable, timeout, and time-budget
mechanics.

Configuration example in .sb_config.json:

    {
      "custom_gates": [
        {
          "name": "no-debugger-imports",
          "description": "Fail if pdb or debugpy is imported",
          "category": "deceptiveness",
          "command": "! grep -rn 'import pdb\\|import debugpy' src/",
          "level": "swab",
          "timeout": 30
        }
      ]
    }

See issue #53 for design rationale.
"""

import logging
import time
from typing import Any, ClassVar, Dict, List, Type

from slopmop.checks.base import BaseCheck, GateCategory, GateLevel
from slopmop.core.result import CheckResult, CheckStatus

logger = logging.getLogger(__name__)

# Default timeout for custom gates (seconds)
DEFAULT_CUSTOM_TIMEOUT = 60


def _resolve_category(key: str) -> GateCategory:
    """Resolve a category key string to a GateCategory enum value.

    Falls back to GENERAL for unrecognised keys.
    """
    cat = GateCategory.from_key(key)
    if cat is None:
        logger.warning(f"Unknown custom gate category '{key}', defaulting to 'general'")
        return GateCategory.GENERAL
    return cat


def _resolve_level(key: str) -> GateLevel:
    """Resolve a level key string to a GateLevel enum value."""
    key_lower = key.lower()
    if key_lower == "scour":
        return GateLevel.SCOUR
    return GateLevel.SWAB


class Flaw:
    """Minimal flaw stub for custom gates — reuses the category's flaw."""

    pass


def make_custom_check_class(
    gate_name: str,
    description: str,
    category_key: str,
    command: str,
    level_str: str = "swab",
    timeout: int = DEFAULT_CUSTOM_TIMEOUT,
) -> Type[BaseCheck]:
    """Dynamically create a BaseCheck subclass for a user-defined gate.

    Each call produces a unique class whose instances behave like a normal
    registered gate.  The shell ``command`` is executed via the subprocess
    runner; exit code 0 means pass, anything else is a failure.

    Args:
        gate_name: Identifier shown in output (e.g. "no-debugger-imports").
        description: Human-readable explanation.
        category_key: Flaw category key (overconfidence, laziness, …).
        command: Shell command to execute.
        level_str: "swab" or "scour".
        timeout: Max seconds before the command is killed.

    Returns:
        A new BaseCheck subclass ready for registry.register().
    """
    resolved_category = _resolve_category(category_key)
    resolved_level = _resolve_level(level_str)

    # Import Flaw from base to provide the flaw property
    from slopmop.checks.base import Flaw as BaseFlaw

    # Map category to flaw (custom gates inherit flaw from category)
    _CATEGORY_TO_FLAW = {
        GateCategory.OVERCONFIDENCE: BaseFlaw.OVERCONFIDENCE,
        GateCategory.DECEPTIVENESS: BaseFlaw.DECEPTIVENESS,
        GateCategory.LAZINESS: BaseFlaw.LAZINESS,
        GateCategory.MYOPIA: BaseFlaw.MYOPIA,
    }
    resolved_flaw = _CATEGORY_TO_FLAW.get(resolved_category, BaseFlaw.LAZINESS)

    class _CustomCheck(BaseCheck):
        """Dynamically generated custom gate."""

        # Store gate definition as class-level attributes so they
        # survive the registry's temp-instance dance.
        _gate_name: ClassVar[str] = gate_name
        _description: ClassVar[str] = description
        _category: ClassVar[GateCategory] = resolved_category
        _command: ClassVar[str] = command
        _timeout: ClassVar[int] = timeout
        _flaw: ClassVar[Any] = resolved_flaw

        level: ClassVar[GateLevel] = resolved_level

        @property
        def name(self) -> str:
            return self._gate_name

        @property
        def display_name(self) -> str:
            return f"🔧 {self._description}"

        @property
        def category(self) -> GateCategory:
            return self._category

        @property
        def flaw(self) -> Any:
            return self._flaw

        @property
        def gate_description(self) -> str:
            return self._description

        def is_applicable(self, project_root: str) -> bool:
            # Custom gates are always applicable — the user defined
            # them for this specific repo.
            return True

        def run(self, project_root: str) -> CheckResult:
            start = time.time()

            try:
                # Run as a shell command so pipes, globs, etc. work
                result = self._runner.run(
                    ["sh", "-c", self._command],
                    cwd=project_root,
                    timeout=self._timeout,
                )
            except Exception as e:
                return self._create_result(
                    status=CheckStatus.ERROR,
                    duration=time.time() - start,
                    error=f"Failed to execute custom gate command: {e}",
                    fix_suggestion=f"Check that the command is valid: {self._command}",
                )

            duration = time.time() - start

            if result.timed_out:
                return self._create_result(
                    status=CheckStatus.FAILED,
                    duration=duration,
                    error=f"Custom gate timed out after {self._timeout}s",
                    fix_suggestion=(
                        f"Increase timeout in .sb_config.json or optimise the command:\n"
                        f"  {self._command}"
                    ),
                )

            combined_output = (result.stdout or "") + (result.stderr or "")

            if result.returncode == 0:
                return self._create_result(
                    status=CheckStatus.PASSED,
                    duration=duration,
                    output=combined_output.strip() or "Custom gate passed",
                )
            else:
                return self._create_result(
                    status=CheckStatus.FAILED,
                    duration=duration,
                    output=combined_output.strip(),
                    error=f"Custom gate failed (exit code {result.returncode})",
                    fix_suggestion=f"Fix the issue reported by: {self._command}",
                )

    # Give the class a meaningful __name__ for debugging
    _CustomCheck.__name__ = f"CustomCheck_{gate_name.replace('-', '_')}"
    _CustomCheck.__qualname__ = _CustomCheck.__name__

    return _CustomCheck


def register_custom_gates(config: Dict[str, Any]) -> List[str]:
    """Parse custom_gates from config and register them with the global registry.

    This should be called after built-in checks are registered and after
    config is loaded, but before checks are executed.

    Args:
        config: The full .sb_config.json dictionary.

    Returns:
        List of registered custom gate full names (e.g. ["laziness:no-debugger"]).
    """
    from slopmop.core.registry import get_registry

    custom_defs = config.get("custom_gates", [])
    if not isinstance(custom_defs, list):
        logger.warning("custom_gates must be a list, ignoring")
        return []

    registry = get_registry()
    registered: List[str] = []

    for i, gate_def in enumerate(custom_defs):
        if not isinstance(gate_def, dict):
            logger.warning(
                f"custom_gates[{i}]: expected object, got {type(gate_def).__name__}"
            )
            continue

        # Required fields
        name = gate_def.get("name")
        command = gate_def.get("command")
        if not name or not command:
            logger.warning(
                f"custom_gates[{i}]: 'name' and 'command' are required, skipping"
            )
            continue

        description = gate_def.get("description", name)
        category_key = gate_def.get("category", "general")
        level_str = gate_def.get("level", "swab")
        timeout = gate_def.get("timeout", DEFAULT_CUSTOM_TIMEOUT)

        # Validate timeout
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            logger.warning(
                f"custom_gates[{i}] ({name}): invalid timeout {timeout}, using default"
            )
            timeout = DEFAULT_CUSTOM_TIMEOUT

        try:
            check_class = make_custom_check_class(
                gate_name=name,
                description=description,
                category_key=category_key,
                command=command,
                level_str=level_str,
                timeout=int(timeout),
            )
            registry.register(check_class)

            # Determine the full name for logging
            temp = check_class({})
            full_name = temp.full_name
            registered.append(full_name)
            logger.debug(f"Registered custom gate: {full_name}")
        except Exception as e:
            logger.warning(f"custom_gates[{i}] ({name}): registration failed: {e}")

    if registered:
        logger.info(f"Registered {len(registered)} custom gate(s)")

    return registered
