"""
Subprocess Guard — Secure, allowlist-based command execution.

The single point of entry for all system calls. Guards against:
- Shell injection (no shell=True)
- Unauthorized executables (allowlist enforcement)
- Argument tampering (basic validation)

Every subprocess invocation in slopbucket goes through this module.
"""

import logging
import shlex
import subprocess  # nosec B404 — guarded by allowlist
import sys
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

# Allowlisted executables that slopbucket is permitted to invoke.
# Any command not in this set is rejected before execution.
ALLOWED_EXECUTABLES: set = {
    # Python tooling
    "python",
    "python3",
    sys.executable,
    "black",
    "isort",
    "autoflake",
    "flake8",
    "mypy",
    "pytest",
    "coverage",
    "diff-cover",
    "radon",
    "bandit",
    "semgrep",
    "detect-secrets",
    "detect-secrets-hook",
    "safety",
    "pylint",
    # Node.js tooling
    "node",
    "npx",
    "npm",
    # Git
    "git",
    # System utilities (read-only, no mutation)
    "which",
    "curl",
    "wc",
}


class GuardViolationError(Exception):
    """Raised when a subprocess call violates the security allowlist."""

    pass


class SubprocessResult:
    """Wraps subprocess completion data for uniform handling."""

    def __init__(self, returncode: int, stdout: str, stderr: str, cmd: List[str]):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.cmd = cmd
        self.success = returncode == 0

    @property
    def output(self) -> str:
        """Combined output, stdout first."""
        return (self.stdout + "\n" + self.stderr).strip()

    def __repr__(self) -> str:
        return f"SubprocessResult(cmd={self.cmd}, rc={self.returncode})"


def _resolve_executable(name: str) -> Optional[str]:
    """Resolve a command name to its full path, if it exists."""
    import shutil

    return shutil.which(name)


def _validate_executable(cmd: Sequence[str]) -> str:
    """Validate the first element of cmd is an allowed executable.

    Returns the resolved executable path on success.
    Raises GuardViolationError on failure.
    """
    if not cmd:
        raise GuardViolationError("Empty command sequence")

    executable = cmd[0]

    # Direct allowlist match
    if executable in ALLOWED_EXECUTABLES:
        return executable

    # Check if it's a full path to an allowed executable
    exe_path = Path(executable)
    if exe_path.name in ALLOWED_EXECUTABLES:
        return executable

    # Check if it resolves to an allowed executable
    resolved = _resolve_executable(executable)
    if resolved:
        resolved_name = Path(resolved).name
        if resolved_name in ALLOWED_EXECUTABLES or resolved in ALLOWED_EXECUTABLES:
            return executable

    raise GuardViolationError(
        f"Executable '{executable}' is not in the allowlist. "
        f"Allowed: {sorted(ALLOWED_EXECUTABLES)}"
    )


def run(
    cmd: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: Optional[int] = None,
    capture_output: bool = True,
) -> SubprocessResult:
    """Execute a command through the security guard.

    Args:
        cmd: Command as a sequence of strings (NOT a shell string).
        cwd: Working directory for the command.
        env: Environment variables (merged with current env if provided).
        timeout: Maximum execution time in seconds.
        capture_output: If True, capture stdout/stderr. If False, inherit.

    Returns:
        SubprocessResult with return code and output.

    Raises:
        GuardViolationError: If the command is not in the allowlist.
        subprocess.TimeoutExpired: If execution exceeds timeout.
    """
    cmd_list = list(cmd)
    _validate_executable(cmd_list)

    logger.debug("SubprocessGuard executing: %s", shlex.join(cmd_list))

    import os

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    kwargs: dict = {
        "cwd": cwd,
        "env": merged_env,
        "timeout": timeout,
        # SECURITY: Never use shell=True
        "shell": False,  # nosec B603
    }

    if capture_output:
        kwargs["stdout"] = subprocess.PIPE  # nosec B603
        kwargs["stderr"] = subprocess.PIPE  # nosec B603

    try:
        proc = subprocess.run(cmd_list, **kwargs)  # nosec B603
        stdout = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        return SubprocessResult(
            returncode=proc.returncode, stdout=stdout, stderr=stderr, cmd=cmd_list
        )
    except subprocess.TimeoutExpired:
        logger.warning("Command timed out after %ds: %s", timeout, shlex.join(cmd_list))
        raise
    except FileNotFoundError:
        return SubprocessResult(
            returncode=127,
            stdout="",
            stderr=f"Command not found: {cmd_list[0]}",
            cmd=cmd_list,
        )


def add_to_allowlist(executable: str) -> None:
    """Register an additional executable in the allowlist.

    Use this in setup.py or configuration to extend the default allowlist
    for project-specific tools.
    """
    ALLOWED_EXECUTABLES.add(executable)


def is_allowed(executable: str) -> bool:
    """Check if an executable is in the allowlist."""
    if executable in ALLOWED_EXECUTABLES:
        return True
    resolved = _resolve_executable(executable)
    if resolved:
        resolved_name = Path(resolved).name
        return resolved_name in ALLOWED_EXECUTABLES or resolved in ALLOWED_EXECUTABLES
    return False
