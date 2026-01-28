"""
E2E check — end-to-end browser tests via Playwright.

Delegates to pytest tests/e2e/ when the directory exists and the
LOOPCLOSER_DEFAULT_PORT_E2E (or TEST_PORT) env var is set.

Like smoke, this check does NOT manage server lifecycle — the host CI
workflow seeds the database and starts the server before invoking
slopbucket.  The check verifies that Playwright is importable and that
test files are present before attempting execution.
"""

import os
import sys
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run


class E2ECheck(BaseCheck):
    """End-to-end Playwright browser tests."""

    @property
    def name(self) -> str:
        return "e2e"

    @property
    def description(self) -> str:
        return "E2E browser tests (Playwright, requires running server)"

    def _detect_server_port(self) -> Optional[str]:
        return (
            os.environ.get("LOOPCLOSER_DEFAULT_PORT_E2E")
            or os.environ.get("TEST_PORT")
            or os.environ.get("PORT")
        )

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        base = working_dir or os.getcwd()
        e2e_dir = os.path.join(base, "tests", "e2e")

        if not os.path.isdir(e2e_dir):
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No tests/e2e/ directory found — E2E check skipped.",
            )

        port = self._detect_server_port()
        if not port:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No E2E server port configured "
                "(set LOOPCLOSER_DEFAULT_PORT_E2E or TEST_PORT). "
                "E2E tests require a running server.",
            )

        # Verify playwright is available
        probe = run(
            [sys.executable, "-c", "import playwright"],
            cwd=base,
        )
        if not probe.success:
            return self._make_result(
                status=CheckStatus.ERROR,
                output="Playwright is not installed.",
                fix_hint="Install: pip install playwright && "
                "python -m playwright install --with-deps chromium",
            )

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "tests/e2e",
            "--tb=short",
            "-v",
            f"--timeout=30",
        ]

        result = run(cmd, cwd=base, timeout=600)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output=self._summary_line(result.stdout),
            )

        if result.returncode == 2:
            return self._make_result(
                status=CheckStatus.ERROR,
                output="E2E test collection error.\n" + result.stdout + result.stderr,
                fix_hint="Check test file syntax and playwright installation.",
            )

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout + result.stderr,
            fix_hint="One or more E2E tests failed. "
            "Verify the server is healthy on port "
            + port
            + " and review browser screenshots if generated.",
        )

    @staticmethod
    def _summary_line(output: str) -> str:
        for line in reversed(output.splitlines()):
            if "passed" in line or "failed" in line:
                return line.strip()
        return "E2E tests completed"
