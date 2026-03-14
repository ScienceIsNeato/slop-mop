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
from typing import Any, ClassVar, Dict, List, Optional, Type, cast

from slopmop.checks.base import BaseCheck, GateCategory, GateLevel
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel
from slopmop.subprocess.runner import SubprocessRunner
from slopmop.subprocess.validator import CommandValidator

logger = logging.getLogger(__name__)

# Default timeout for custom gates (seconds)
DEFAULT_CUSTOM_TIMEOUT = 60


class _TrustedCommandValidator(CommandValidator):
    """Permissive validator for user-defined custom gate commands.

    Custom gate commands are defined by the repo owner in .sb_config.json,
    not from external input.  They deliberately use shell features (pipes,
    redirects, sub-shells) and must not be blocked by injection checks.

    The executable whitelist is still enforced — only the argument-level
    pattern scan is relaxed.
    """

    def _validate_argument(self, arg: str, position: int) -> None:
        """Skip argument validation for trusted user commands."""


# Module-level runner for custom gates (lazy-initialised)
_custom_runner: Optional[SubprocessRunner] = None


def _get_custom_runner() -> SubprocessRunner:
    """Return a SubprocessRunner that uses the trusted validator."""
    global _custom_runner
    if _custom_runner is None:
        _custom_runner = SubprocessRunner(validator=_TrustedCommandValidator())
    return _custom_runner


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


def make_custom_check_class(
    gate_name: str,
    description: str,
    category_key: str,
    command: str,
    level_str: str = "swab",
    timeout: int = DEFAULT_CUSTOM_TIMEOUT,
    fix_command: Optional[str] = None,
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
        _fix_command: ClassVar[Optional[str]] = fix_command
        _timeout: ClassVar[int] = timeout
        _flaw: ClassVar[Any] = resolved_flaw
        is_custom_gate: ClassVar[bool] = True

        level: ClassVar[GateLevel] = resolved_level

        def __init__(
            self,
            config: Dict[str, Any],
            runner: Optional[SubprocessRunner] = None,
        ):
            # Use the trusted runner by default so user-defined commands
            # containing shell metacharacters (pipes, redirects, etc.)
            # are not rejected by the strict CommandValidator.
            super().__init__(config, runner=runner or _get_custom_runner())

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

        def can_auto_fix(self) -> bool:
            return bool(self._fix_command)

        def auto_fix(self, project_root: str) -> bool:
            if not self._fix_command:
                return False
            result = self._runner.run(
                ["sh", "-c", self._fix_command],
                cwd=project_root,
                timeout=self._timeout,
            )
            return bool(result.returncode == 0 and not result.timed_out)

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
                msg = f"Custom gate timed out after {self._timeout}s"
                return self._create_result(
                    status=CheckStatus.FAILED,
                    duration=duration,
                    error=msg,
                    fix_suggestion=(
                        f"Increase timeout in .sb_config.json or optimise the command:\n"
                        f"  {self._command}"
                    ),
                    findings=[Finding(message=msg, level=FindingLevel.ERROR)],
                )

            combined_output = (result.stdout or "") + (result.stderr or "")

            if result.returncode == 0:
                return self._create_result(
                    status=CheckStatus.PASSED,
                    duration=duration,
                    output=combined_output.strip() or "Custom gate passed",
                )
            else:
                msg = f"Custom gate failed (exit code {result.returncode})"
                return self._create_result(
                    status=CheckStatus.FAILED,
                    duration=duration,
                    output=combined_output.strip(),
                    error=msg,
                    fix_suggestion=f"Fix the issue reported by: {self._command}",
                    findings=[Finding(message=msg, level=FindingLevel.ERROR)],
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

    custom_defs: Any = config.get("custom_gates", [])
    if not isinstance(custom_defs, list):
        logger.warning("custom_gates must be a list, ignoring")
        return []

    gate_list: List[Any] = cast(List[Any], custom_defs)
    registry = get_registry()
    registered: List[str] = []

    for i, raw_def in enumerate(gate_list):
        if not isinstance(raw_def, dict):
            logger.warning(
                f"custom_gates[{i}]: expected object, got {type(raw_def).__name__}"
            )
            continue
        gate_def: Dict[str, Any] = cast(Dict[str, Any], raw_def)

        # Required fields
        name: str = str(gate_def.get("name", ""))
        command: str = str(gate_def.get("command", ""))
        if not name or not command:
            logger.warning(
                f"custom_gates[{i}]: 'name' and 'command' are required, skipping"
            )
            continue

        description: str = str(gate_def.get("description", name))
        category_key: str = str(gate_def.get("category", "general"))
        level_str: str = str(gate_def.get("level", "swab"))
        fix_command: Optional[str] = None
        raw_fix_command: Any = gate_def.get("fix_command")
        if isinstance(raw_fix_command, str) and raw_fix_command.strip():
            fix_command = raw_fix_command.strip()
        raw_timeout: Any = gate_def.get("timeout", DEFAULT_CUSTOM_TIMEOUT)

        # Validate timeout
        timeout_val: int = DEFAULT_CUSTOM_TIMEOUT
        if isinstance(raw_timeout, (int, float)) and raw_timeout > 0:
            timeout_val = int(raw_timeout)
        else:
            logger.warning(
                f"custom_gates[{i}] ({name}): invalid timeout {raw_timeout}, "
                "using default"
            )

        try:
            check_class: Type[BaseCheck] = make_custom_check_class(
                gate_name=name,
                description=description,
                category_key=category_key,
                command=command,
                level_str=level_str,
                timeout=timeout_val,
                fix_command=fix_command,
            )
            registry.register(check_class)

            # Determine the full name for logging
            temp: BaseCheck = check_class({})
            full_name: str = temp.full_name
            registered.append(full_name)
            logger.debug(f"Registered custom gate: {full_name}")
        except Exception as e:
            logger.warning(f"custom_gates[{i}] ({name}): registration failed: {e}")

    if registered:
        logger.debug(f"Registered {len(registered)} custom gate(s)")

    return registered
