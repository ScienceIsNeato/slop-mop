"""
Python duplication check — jscpd copy-paste detection.

Flags code duplication above the configured threshold.
Works across Python (and JS if present) source files.
"""

from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run

DUPLICATION_THRESHOLD = 5  # Percent
MIN_LINES = 3  # Minimum lines to count as duplication


class PythonDuplicationCheck(BaseCheck):
    """jscpd-based code duplication detection."""

    @property
    def name(self) -> str:
        return "python-duplication"

    @property
    def description(self) -> str:
        return f"Code duplication detection (max {DUPLICATION_THRESHOLD}%)"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        cmd = [
            "npx",
            "jscpd",
            ".",
            "--min-lines",
            str(MIN_LINES),
            "--threshold",
            str(DUPLICATION_THRESHOLD),
            "--reporters",
            "console",
            "--ignore",
            "**/__tests__/**,**/tests/**,**/venv/**,**/.venv/**,**/node_modules/**,**/archives/**",
            "--format",
            "python",
        ]
        result = run(cmd, cwd=working_dir, timeout=120)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output="Duplication within limits",
            )

        output = result.stdout or result.stderr
        return self._make_result(
            status=CheckStatus.FAILED,
            output=output,
            fix_hint=f"Code duplication exceeds {DUPLICATION_THRESHOLD}%. Extract common logic into shared utilities.",
        )
