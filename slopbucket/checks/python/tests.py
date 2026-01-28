"""Python test execution check using pytest."""

import time

from slopbucket.checks.base import BaseCheck, PythonCheckMixin
from slopbucket.core.result import CheckResult, CheckStatus


class PythonTestsCheck(BaseCheck, PythonCheckMixin):
    """Python test execution check.

    Runs pytest to execute unit and integration tests.
    Generates coverage data for use by coverage checks.
    """

    @property
    def name(self) -> str:
        return "python-tests"

    @property
    def display_name(self) -> str:
        return "🧪 Python Tests (pytest)"

    def is_applicable(self, project_root: str) -> bool:
        return self.is_python_project(project_root)

    def run(self, project_root: str) -> CheckResult:
        """Run pytest."""
        start_time = time.time()

        # Run pytest with coverage to generate coverage.xml
        result = self._run_command(
            [
                "python", "-m", "pytest",
                "--cov=.",
                "--cov-report=xml:coverage.xml",
                "--cov-report=term-missing",
                "-v",
                "--tb=short",
            ],
            cwd=project_root,
            timeout=300,  # 5 minutes for tests
        )

        duration = time.time() - start_time

        if result.timed_out:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error="Tests timed out after 5 minutes",
                fix_suggestion="Check for infinite loops or slow tests",
            )

        if not result.success:
            # Extract failure summary
            lines = result.output.split("\n")
            failed_tests = [l for l in lines if "FAILED" in l]

            error_msg = f"{len(failed_tests)} test(s) failed"
            if failed_tests:
                error_msg += ":\n" + "\n".join(failed_tests[:5])

            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error=error_msg,
                fix_suggestion="Run: pytest -v to see detailed test failures",
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output=result.output,
        )
