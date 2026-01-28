"""
Python test runner — Pytest with coverage generation.

Executes unit and integration tests. Generates coverage.xml
for downstream coverage checks. Supports parallel test execution.
"""

import sys
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run


class PythonTestsCheck(BaseCheck):
    """Pytest test runner with coverage instrumentation."""

    @property
    def name(self) -> str:
        return "python-tests"

    @property
    def description(self) -> str:
        return "Pytest unit + integration tests with coverage generation"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        import os

        base = working_dir or os.getcwd()

        # Discover test directories
        test_dirs = []
        for candidate in ["tests/unit", "tests/integration", "tests"]:
            path = os.path.join(base, candidate)
            if os.path.isdir(path):
                test_dirs.append(candidate)
                if candidate == "tests":
                    break  # Don't add subdirs if parent exists alone

        if not test_dirs:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No test directories found.",
            )

        cmd = [
            sys.executable,
            "-m",
            "pytest",
        ] + test_dirs + [
            "--cov=src",
            "--cov-report=term-missing",
            "--cov-report=xml:coverage.xml",
            "-v",
            "--tb=short",
        ]

        result = run(cmd, cwd=working_dir, timeout=600)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output=self._extract_summary(result.stdout),
            )

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout + result.stderr,
            fix_hint="Fix failing tests. Run: pytest tests/ -v --tb=long for detailed output.",
        )

    def _extract_summary(self, output: str) -> str:
        """Extract the pytest summary line from output."""
        for line in reversed(output.splitlines()):
            if "passed" in line or "failed" in line or "error" in line:
                return line.strip()
        return "Tests completed"
