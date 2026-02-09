"""Python test execution check using pytest."""

import time
from typing import List

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    GateCategory,
    PythonCheckMixin,
)
from slopmop.checks.constants import (
    SKIP_NOT_PYTHON_PROJECT,
    has_python_test_files,
    skip_reason_no_test_files,
)
from slopmop.core.result import CheckResult, CheckStatus


class PythonTestsCheck(BaseCheck, PythonCheckMixin):
    """Python test execution via pytest.

    Wraps pytest with coverage instrumentation. Runs all tests and
    generates coverage.xml for the coverage gate. If tests fail,
    reports the specific failing test names.

    Profiles: commit, pr

    Configuration:
      test_dirs: ["tests"] — default pytest discovery directory.
      timeout: 300 — 5-minute timeout. Long enough for large suites,
          short enough to catch infinite loops.

    Common failures:
      Test failures: Output lists the specific failing test names.
          Run `pytest -v --tb=long <test_file>` for full tracebacks.
      Timeout: Suite took > 5 minutes. Look for infinite loops,
          missing mocks on network calls, or slow fixtures.
      Import errors: A test imports something that doesn't exist.
          Usually a missing dependency or renamed module.

    Re-validate:
      ./sm validate python:tests --verbose
    """

    @property
    def name(self) -> str:
        return "tests"

    @property
    def display_name(self) -> str:
        return "🧪 Tests (pytest)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.PYTHON

    @property
    def depends_on(self) -> List[str]:
        return ["python:lint-format"]

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="test_dirs",
                field_type="string[]",
                default=["tests"],
                description="Directories containing test files",
            ),
            ConfigField(
                name="timeout",
                field_type="integer",
                default=300,
                description="Test execution timeout in seconds",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Applicable only if there are Python test files to run."""
        if not self.is_python_project(project_root):
            return False
        test_dirs = self.config.get("test_dirs", ["tests"])
        return has_python_test_files(project_root, test_dirs)

    def skip_reason(self, project_root: str) -> str:
        """Return skip reason when test prerequisites are missing."""
        if not self.is_python_project(project_root):
            return SKIP_NOT_PYTHON_PROJECT
        test_dirs = self.config.get("test_dirs", ["tests"])
        return skip_reason_no_test_files(test_dirs)

    def run(self, project_root: str) -> CheckResult:
        """Run pytest."""
        start_time = time.time()

        # Run pytest with coverage to generate coverage.xml
        result = self._run_command(
            [
                self.get_project_python(project_root),
                "-m",
                "pytest",
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
            failed_tests = [line for line in lines if "FAILED" in line]

            # Check if failure is due to coverage threshold (not test failures)
            coverage_fail = any(
                "coverage failure" in line.lower()
                or "fail required test coverage" in line.lower()
                for line in lines
            )

            if coverage_fail and not failed_tests:
                # All tests passed but coverage is low - don't fail here,
                # let the coverage check handle it
                return self._create_result(
                    status=CheckStatus.PASSED,
                    duration=duration,
                    output=result.output,
                )

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
