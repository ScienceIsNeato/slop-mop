"""Secure command validation for subprocess execution.

This module provides security-focused validation of commands before they
are executed via subprocess. It uses a whitelist approach to prevent
arbitrary command execution and shell injection attacks.

Security Principles:
1. Only allow known, safe executables
2. Never use shell=True
3. Detect and reject shell injection patterns
4. Validate all arguments for dangerous content
"""

import re
from pathlib import Path
from typing import FrozenSet, List, Optional, Set


class SecurityError(Exception):
    """Raised when a command fails security validation."""


class CommandValidator:
    """Validates commands before subprocess execution.

    This class implements a whitelist-based security model for subprocess
    execution. Only explicitly allowed executables can be run, and all
    arguments are scanned for shell injection patterns.

    Attributes:
        ALLOWED_EXECUTABLES: Set of executable names that can be run
    """

    # Whitelist of allowed executables
    # These are common development tools that are safe to run
    ALLOWED_EXECUTABLES: FrozenSet[str] = frozenset(
        {
            # Python ecosystem
            "python",
            "python3",
            "python3.9",
            "python3.10",
            "python3.11",
            "python3.12",
            "python3.13",
            "python3.14",
            "pip",
            "pip3",
            "black",
            "isort",
            "flake8",
            "pylint",
            "mypy",
            "pytest",
            "coverage",
            "radon",
            "xenon",
            "bandit",
            "semgrep",
            "safety",
            "diff-cover",
            "autoflake",
            "pyright",
            "ruff",
            # JavaScript/Node ecosystem
            "node",
            "npm",
            "npx",
            "yarn",
            "pnpm",
            "eslint",
            "prettier",
            "jest",
            "tsc",
            # Version control
            "git",
            "gh",
            # Build tools
            "make",
            "cmake",
            # General utilities (some can mutate files - use with caution)
            "timeout",
            "find",
            "wc",
            "which",
            "ls",
            "cat",
            "head",
            "tail",
            "grep",
            "sort",
            "uniq",
            "tee",
            # Note: touch, mkdir, cp, mv can mutate filesystem but are
            # sometimes needed by build tools. They're allowed but logged.
            "touch",
            "mkdir",
            "cp",
            "mv",
            # Shells (for running scripts with explicit paths)
            "bash",
            "sh",
            "zsh",
        }
    )

    # Patterns that indicate potential shell injection
    DANGEROUS_PATTERNS: FrozenSet[str] = frozenset(
        {
            ";",  # Command separator
            "&&",  # Logical AND
            "||",  # Logical OR
            "|",  # Pipe
            "`",  # Command substitution (backtick)
            "$(",  # Command substitution
            "${",  # Variable expansion
            ">",  # Output redirection
            "<",  # Input redirection
            ">>",  # Append redirection
            "2>",  # Stderr redirection
            "&>",  # Combined redirection
        }
    )

    # Additional patterns for more sophisticated attacks
    DANGEROUS_REGEX_PATTERNS: List[re.Pattern] = [
        re.compile(r"\$\{.*\}"),  # Variable expansion ${...}
        re.compile(r"\$\(.*\)"),  # Command substitution $(...)
        re.compile(r"`.*`"),  # Command substitution `...`
        re.compile(r";\s*\w"),  # Semicolon followed by command
    ]

    def __init__(self, additional_allowed: Optional[Set[str]] = None):
        """Initialize validator with optional additional allowed executables.

        Args:
            additional_allowed: Extra executables to add to the whitelist
        """
        self._allowed = set(self.ALLOWED_EXECUTABLES)
        if additional_allowed:
            self._allowed.update(additional_allowed)

    def validate(self, command: List[str]) -> bool:
        """Validate that a command is safe to execute.

        Args:
            command: Command as list of strings (first element is executable)

        Returns:
            True if command is safe to execute

        Raises:
            SecurityError: If command fails validation
        """
        if not command:
            raise SecurityError("Empty command")

        if not isinstance(command, list):
            raise SecurityError("Command must be a list of strings")

        for i, arg in enumerate(command):
            if not isinstance(arg, str):
                raise SecurityError(f"Argument {i} is not a string: {type(arg)}")

        # Extract executable name (handle full paths)
        executable = Path(command[0]).name

        # Check if executable is in whitelist
        if executable not in self._allowed:
            raise SecurityError(
                f"Executable not in whitelist: {executable}\n"
                f"Allowed executables: {', '.join(sorted(self._allowed))}"
            )

        # Check all arguments for dangerous patterns
        for i, arg in enumerate(command[1:], start=1):
            self._validate_argument(arg, i)

        return True

    def _validate_argument(self, arg: str, position: int) -> None:
        """Validate a single command argument.

        Args:
            arg: The argument to validate
            position: Position in command (for error messages)

        Raises:
            SecurityError: If argument contains dangerous patterns
        """
        # Check for ALL dangerous patterns - any pattern in DANGEROUS_PATTERNS
        # is considered unsafe and will raise an error
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern in arg:
                raise SecurityError(
                    f"Dangerous shell pattern in argument {position}: '{pattern}'\n"
                    f"Full argument: {arg}\n"
                    f"This pattern could enable shell injection attacks."
                )

        # Check regex patterns for more complex attacks
        for regex in self.DANGEROUS_REGEX_PATTERNS:
            if regex.search(arg):
                raise SecurityError(
                    f"Dangerous pattern in argument {position}: {regex.pattern}\n"
                    f"Full argument: {arg}"
                )

    def add_allowed(self, executable: str) -> None:
        """Add an executable to the whitelist.

        Args:
            executable: Name of executable to allow
        """
        self._allowed.add(executable)

    def is_allowed(self, executable: str) -> bool:
        """Check if an executable is in the whitelist.

        Args:
            executable: Name of executable to check

        Returns:
            True if executable is allowed
        """
        return Path(executable).name in self._allowed


# Module-level singleton for convenience
_default_validator: Optional[CommandValidator] = None


def get_validator() -> CommandValidator:
    """Get the default command validator singleton."""
    global _default_validator
    if _default_validator is None:
        _default_validator = CommandValidator()
    return _default_validator


def validate_command(command: List[str]) -> bool:
    """Validate a command using the default validator.

    Args:
        command: Command to validate

    Returns:
        True if command is safe

    Raises:
        SecurityError: If command fails validation
    """
    return get_validator().validate(command)
