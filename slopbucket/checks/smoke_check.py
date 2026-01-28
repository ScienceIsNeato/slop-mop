"""
Smoke check — critical-path Selenium/browser tests requiring a live server.

The smoke check delegates to pytest tests/smoke/ when a running server
is detected (via TEST_PORT or PORT env vars).  It is repo-specific
infrastructure: slopbucket orchestrates the pytest invocation but does
NOT start or seed a server — that is the host CI's responsibility.

Skips gracefully when:
  - No tests/smoke/ directory exists
  - No server port is configured (TEST_PORT / PORT)
  - selenium is not installed
"""

import os
import sys
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run


class SmokeCheck(BaseCheck):
    """Smoke tests — critical-path browser validation against a live server."""

    @property
    def name(self) -> str:
        return "smoke"

    @property
    def description(self) -> str:
        return "Smoke tests (Selenium, requires running server)"

    def _detect_server_port(self) -> Optional[str]:
        """Return the server port from env, or None."""
        return os.environ.get("TEST_PORT") or os.environ.get("PORT")

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        base = working_dir or os.getcwd()
        smoke_dir = os.path.join(base, "tests", "smoke")

        if not os.path.isdir(smoke_dir):
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No tests/smoke/ directory found — smoke check skipped.",
            )

        port = self._detect_server_port()
        if not port:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No server port configured (set TEST_PORT or PORT). "
                "Smoke tests require a running server — the CI workflow "
                "is responsible for starting and seeding it.",
            )

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "tests/smoke",
            "--tb=short",
            "-v",
        ]

        result = run(cmd, cwd=base, timeout=300)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output=self._summary_line(result.stdout),
            )

        # Distinguish test failures from infrastructure errors
        if result.returncode == 2:
            return self._make_result(
                status=CheckStatus.ERROR,
                output="Smoke test collection error (possibly missing selenium).\n"
                + result.stdout
                + result.stderr,
                fix_hint="Install selenium: pip install selenium. "
                "Ensure the server is running on port " + port + ".",
            )

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout + result.stderr,
            fix_hint="One or more smoke tests failed. "
            "Verify the server is healthy on port "
            + port
            + " and check test output above.",
        )

    @staticmethod
    def _summary_line(output: str) -> str:
        for line in reversed(output.splitlines()):
            if "passed" in line or "failed" in line:
                return line.strip()
        return "Smoke tests completed"
