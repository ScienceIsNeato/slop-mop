"""
Integration check — database-backed integration tests.

Targets tests/integration/ specifically (not tests/unit/).
Requires a seeded database; the host CI workflow is responsible for
database setup and seeding before invoking slopbucket.

Distinct from python-tests which runs the full test suite (unit +
integration combined).  This check isolates integration tests for
environments where a running server or seeded database is required.
"""

import os
import sys
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run


class IntegrationCheck(BaseCheck):
    """Integration tests targeting tests/integration/ with database."""

    @property
    def name(self) -> str:
        return "integration"

    @property
    def description(self) -> str:
        return "Integration tests (database-backed, tests/integration/)"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        base = working_dir or os.getcwd()
        integration_dir = os.path.join(base, "tests", "integration")

        if not os.path.isdir(integration_dir):
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No tests/integration/ directory found — integration check skipped.",
            )

        # Verify DATABASE_URL is configured
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="DATABASE_URL not set. "
                "Integration tests require a seeded database — "
                "the CI workflow must configure this.",
            )

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration",
            "--tb=short",
            "-v",
        ]

        result = run(cmd, cwd=base, timeout=300)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output=self._summary_line(result.stdout),
            )

        if result.returncode == 2:
            return self._make_result(
                status=CheckStatus.ERROR,
                output="Integration test collection error.\n"
                + result.stdout
                + result.stderr,
                fix_hint="Check test file syntax and database configuration.",
            )

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout + result.stderr,
            fix_hint="Integration test failures detected. "
            "Verify DATABASE_URL is correctly seeded.",
        )

    @staticmethod
    def _summary_line(output: str) -> str:
        for line in reversed(output.splitlines()):
            if "passed" in line or "failed" in line:
                return line.strip()
        return "Integration tests completed"
