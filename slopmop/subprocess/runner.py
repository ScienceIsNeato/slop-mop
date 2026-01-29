"""Secure subprocess execution with validation and timeout handling.

This module provides a secure interface for running subprocesses. All commands
are validated before execution, and proper timeout handling is implemented.
"""

import logging
import subprocess  # nosec B404 - subprocess is core to this module's purpose
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .validator import CommandValidator, get_validator

logger = logging.getLogger(__name__)


@dataclass
class SubprocessResult:
    """Result of a subprocess execution.

    Attributes:
        returncode: Exit code of the process
        stdout: Captured standard output
        stderr: Captured standard error
        duration: Execution time in seconds
        timed_out: Whether the process was killed due to timeout
    """

    returncode: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False

    @property
    def success(self) -> bool:
        """Return True if process exited successfully."""
        return self.returncode == 0 and not self.timed_out

    @property
    def output(self) -> str:
        """Return combined stdout and stderr."""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(self.stderr)
        return "\n".join(parts)


class SubprocessRunner:
    """Secure subprocess runner with validation and process management.

    This class provides a safe interface for running subprocesses:
    - All commands are validated before execution
    - Processes can be tracked and terminated
    - Proper timeout handling with cleanup
    - Thread-safe process tracking
    """

    DEFAULT_TIMEOUT = 120  # 2 minutes
    MAX_TIMEOUT = 600  # 10 minutes

    def __init__(
        self,
        validator: Optional[CommandValidator] = None,
        default_timeout: int = DEFAULT_TIMEOUT,
    ):
        """Initialize the subprocess runner.

        Args:
            validator: Command validator to use (default: global validator)
            default_timeout: Default timeout in seconds
        """
        self._validator = validator or get_validator()
        self._default_timeout = min(default_timeout, self.MAX_TIMEOUT)
        self._process_lock = threading.Lock()
        self._running_processes: Dict[int, subprocess.Popen] = {}

    def run(
        self,
        command: List[str],
        timeout: Optional[int] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        capture_output: bool = True,
    ) -> SubprocessResult:
        """Run a command and wait for completion.

        Args:
            command: Command to run as list of strings
            timeout: Timeout in seconds (None = use default)
            cwd: Working directory for the command
            env: Environment variables (None = inherit)
            capture_output: Whether to capture stdout/stderr

        Returns:
            SubprocessResult with exit code and output

        Raises:
            SecurityError: If command fails validation
        """
        # Validate command before execution
        self._validator.validate(command)

        effective_timeout = min(timeout or self._default_timeout, self.MAX_TIMEOUT)
        start_time = time.time()

        logger.debug(f"Running command: {' '.join(command)}")

        try:
            # Start the process
            # SECURITY: Never use shell=True
            process = subprocess.Popen(  # nosec B603 - commands are validated by CommandValidator
                command,
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                cwd=cwd,
                env=env,
                text=True,
            )

            # Track the process
            with self._process_lock:
                self._running_processes[process.pid] = process

            try:
                # Wait for completion with timeout
                stdout, stderr = process.communicate(timeout=effective_timeout)
                duration = time.time() - start_time

                return SubprocessResult(
                    returncode=process.returncode,
                    stdout=stdout or "",
                    stderr=stderr or "",
                    duration=duration,
                    timed_out=False,
                )

            except subprocess.TimeoutExpired:
                # Kill the process on timeout
                process.kill()
                stdout, stderr = process.communicate()
                duration = time.time() - start_time

                logger.warning(
                    f"Command timed out after {effective_timeout}s: {' '.join(command)}"
                )

                return SubprocessResult(
                    returncode=-1,
                    stdout=stdout or "",
                    stderr=f"Command timed out after {effective_timeout}s\n{stderr or ''}",
                    duration=duration,
                    timed_out=True,
                )

            finally:
                # Remove from tracking
                with self._process_lock:
                    self._running_processes.pop(process.pid, None)

        except FileNotFoundError as e:
            duration = time.time() - start_time
            return SubprocessResult(
                returncode=-1,
                stdout="",
                stderr=f"Command not found: {command[0]}\n{str(e)}",
                duration=duration,
                timed_out=False,
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Subprocess error: {e}")
            return SubprocessResult(
                returncode=-1,
                stdout="",
                stderr=str(e),
                duration=duration,
                timed_out=False,
            )

    def run_with_retry(
        self,
        command: List[str],
        max_retries: int = 1,
        timeout: Optional[int] = None,
        cwd: Optional[str] = None,
    ) -> SubprocessResult:
        """Run a command with automatic retry on failure.

        Args:
            command: Command to run
            max_retries: Maximum number of retry attempts
            timeout: Timeout per attempt
            cwd: Working directory

        Returns:
            SubprocessResult from last attempt
        """
        last_result = None

        for attempt in range(max_retries + 1):
            result = self.run(command, timeout=timeout, cwd=cwd)

            if result.success:
                return result

            last_result = result
            if attempt < max_retries:
                logger.info(
                    f"Retry {attempt + 1}/{max_retries} for: {' '.join(command)}"
                )

        return last_result  # type: ignore

    def start_background(
        self,
        command: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Tuple[subprocess.Popen, int]:
        """Start a process in the background.

        Args:
            command: Command to run
            cwd: Working directory
            env: Environment variables

        Returns:
            Tuple of (process object, pid)

        Raises:
            SecurityError: If command fails validation
        """
        self._validator.validate(command)

        process = (
            subprocess.Popen(  # nosec B603 - commands are validated by CommandValidator
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                text=True,
            )
        )

        with self._process_lock:
            self._running_processes[process.pid] = process

        return process, process.pid

    def terminate_all(self) -> int:
        """Terminate all tracked running processes.

        Returns:
            Number of processes terminated
        """
        with self._process_lock:
            processes = list(self._running_processes.values())

        count = 0
        for process in processes:
            try:
                process.terminate()
                process.wait(timeout=5)
                count += 1
            except subprocess.TimeoutExpired:
                process.kill()
                count += 1
            except Exception as e:
                logger.warning(f"Failed to terminate process {process.pid}: {e}")

        with self._process_lock:
            self._running_processes.clear()

        return count

    def is_running(self, pid: int) -> bool:
        """Check if a process is still running.

        Args:
            pid: Process ID to check

        Returns:
            True if process is running
        """
        with self._process_lock:
            if pid not in self._running_processes:
                return False
            return self._running_processes[pid].poll() is None


# Module-level singleton for convenience
_default_runner: Optional[SubprocessRunner] = None


def get_runner() -> SubprocessRunner:
    """Get the default subprocess runner singleton."""
    global _default_runner
    if _default_runner is None:
        _default_runner = SubprocessRunner()
    return _default_runner


def run_command(
    command: List[str],
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
) -> SubprocessResult:
    """Run a command using the default runner.

    Args:
        command: Command to run
        timeout: Timeout in seconds
        cwd: Working directory

    Returns:
        SubprocessResult with exit code and output
    """
    return get_runner().run(command, timeout=timeout, cwd=cwd)
