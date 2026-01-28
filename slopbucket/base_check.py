"""
Base check abstract class — the interface every check must satisfy.

All checks in slopbucket.checks.* subclass this. The runner interacts
only with this interface, never with concrete check classes directly.
"""

import time
from abc import ABC, abstractmethod
from typing import Optional

from slopbucket.result import CheckResult, CheckStatus


class BaseCheck(ABC):
    """Abstract base class for all quality checks.

    Subclasses implement ``execute()`` which returns a CheckResult.
    The runner handles timing, error wrapping, and parallel scheduling.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique check identifier (e.g. 'python-format')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this check validates."""
        ...

    @abstractmethod
    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        """Run the check and return a result.

        Args:
            working_dir: Root directory of the repository being validated.
                        If None, use current working directory.

        Returns:
            CheckResult with status, output, and optional fix hints.
        """
        ...

    def _make_result(
        self,
        status: CheckStatus,
        output: str = "",
        fix_hint: str = "",
        duration: float = 0.0,
        details: Optional[dict] = None,
    ) -> CheckResult:
        """Helper to construct a CheckResult with this check's metadata."""
        return CheckResult(
            name=self.name,
            status=status,
            output=output,
            fix_hint=fix_hint,
            duration_secs=round(duration, 2),
            details=details or {},
        )

    def _tool_available(
        self, tool_name: str, working_dir: Optional[str] = None
    ) -> bool:
        """Check if a CLI tool is installed and accessible."""
        from slopbucket.subprocess_guard import run

        result = run(["which", tool_name], cwd=working_dir)
        return result.success

    def run_timed(self, working_dir: Optional[str] = None) -> CheckResult:
        """Execute the check with timing instrumentation.

        This is what the runner calls. Don't override this.
        """
        start = time.time()
        try:
            result = self.execute(working_dir)
            result.duration_secs = round(time.time() - start, 2)
            return result
        except Exception as e:
            duration = round(time.time() - start, 2)
            return self._make_result(
                status=CheckStatus.ERROR,
                output=f"Check encountered an unexpected error: {e}",
                fix_hint="This is likely a slopbucket bug — check tool installation.",
                duration=duration,
            )
