"""Python test execution check using pytest."""

import re
import time
from typing import List

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    ToolContext,
)
from slopmop.checks.constants import (
    SKIP_NOT_PYTHON_PROJECT,
    TESTS_TIMED_OUT_MSG,
    has_python_test_files,
    python_no_tests_fix_suggestion,
    skip_reason_no_test_files,
)
from slopmop.checks.mixins import PythonCheckMixin
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

# pytest's short-summary line format is stable across 6.x/7.x/8.x:
#   FAILED tests/test_foo.py::TestBar::test_baz - AssertionError: expected 5, got 3
# The `- reason` suffix is optional (pytest omits it when there's no
# short repr, e.g. on bare `assert False`).
_PYTEST_FAILED_RE = re.compile(
    r"^FAILED\s+(?P<path>\S+\.py)::(?P<nodeid>\S+)(?:\s+-\s+(?P<reason>.+))?$"
)


def _parse_failed_lines(failed_tests: List[str]) -> List[Finding]:
    """Turn pytest FAILED lines into structured findings.

    When the line matches pytest's short-summary format we extract the
    bare test name (last ``::`` segment) and the assertion summary.
    Unparseable lines still surface as findings but without a
    ``fix_strategy`` — we can't compute one honestly.
    """
    structured: List[Finding] = []
    for line in failed_tests:
        m = _PYTEST_FAILED_RE.match(line.strip())
        if not m:
            rest = line.split("FAILED", 1)[-1].strip()
            path = rest.split("::", 1)[0]
            structured.append(
                Finding(
                    message=rest,
                    file=path if path.endswith(".py") else None,
                )
            )
            continue

        path = m.group("path")
        test_name = m.group("nodeid").rsplit("::", 1)[-1]
        reason = m.group("reason")
        msg = f"{test_name} failed: {reason}" if reason else f"{test_name} failed"
        structured.append(
            Finding(
                message=msg,
                file=path,
                rule_id="test-failure",
                fix_strategy=(
                    f"Test {test_name} expects different behaviour. "
                    f"{f'Pytest summary: {reason}. ' if reason else ''}"
                    f"Read the assertion, decide whether the test or "
                    f"the code is wrong, fix one."
                ),
            )
        )
    return structured


class PythonTestsCheck(BaseCheck, PythonCheckMixin):
    """Python test execution via pytest.

    Wraps pytest with coverage instrumentation. Runs all tests and
    generates coverage.xml for the coverage gate. If tests fail,
    reports the specific failing test names.

    Level: swab

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

    Re-check:
      sm swab -g overconfidence:untested-code.py --verbose
    """

    tool_context = ToolContext.PROJECT
    role = CheckRole.FOUNDATION

    @property
    def name(self) -> str:
        return "untested-code.py"

    @property
    def display_name(self) -> str:
        return "🧪 Tests (pytest)"

    @property
    def gate_description(self) -> str:
        return "🧪 Runs pytest — code must actually pass its tests"

    @property
    def category(self) -> GateCategory:
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

    @property
    def depends_on(self) -> List[str]:
        return ["laziness:sloppy-formatting.py"]

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="test_dirs",
                field_type="string[]",
                default=["tests"],
                description="Directories containing test files",
                permissiveness="more_is_stricter",
            ),
            ConfigField(
                name="timeout",
                field_type="integer",
                default=300,
                description="Test execution timeout in seconds",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Applicable to Python projects; run() enforces test presence."""
        return self.is_python_project(project_root)

    def skip_reason(self, project_root: str) -> str:
        """Return skip reason when test prerequisites are missing."""
        if not self.is_python_project(project_root):
            return SKIP_NOT_PYTHON_PROJECT
        return "Python tests check not applicable"

    def run(self, project_root: str) -> CheckResult:
        """Run pytest."""
        start_time = time.time()
        test_dirs = self.config.get("test_dirs", ["tests"])
        if not has_python_test_files(project_root, test_dirs):
            message = skip_reason_no_test_files(test_dirs)
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=time.time() - start_time,
                error=message,
                output=message,
                fix_suggestion=python_no_tests_fix_suggestion(
                    test_dirs, self.verify_command
                ),
                findings=[Finding(message=message, level=FindingLevel.ERROR)],
            )

        # PROJECT check: bail early when no project venv exists
        venv_warn = self.check_project_venv_or_warn(project_root, start_time)
        if venv_warn is not None:
            return venv_warn

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
                error=TESTS_TIMED_OUT_MSG,
                fix_suggestion="Check for infinite loops or slow tests",
                findings=[
                    Finding(message=TESTS_TIMED_OUT_MSG, level=FindingLevel.ERROR)
                ],
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
                fix_suggestion=(
                    "Each failure above names the failing test and "
                    "assertion. Fix the code (or the test, if the "
                    "test's expectation is stale). Verify with: " + self.verify_command
                ),
                findings=_parse_failed_lines(failed_tests),
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output=result.output,
        )
