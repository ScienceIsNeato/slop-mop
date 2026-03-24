"""Python test execution check using pytest."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from slopmop.subprocess.runner import SubprocessResult

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


def _is_failed_summary_line(line: str) -> bool:
    """Return True for pytest short-summary failure lines only.

    Pytest progress output can include tokens like ``FAILED [ 31%]``.
    Those are status markers, not actionable short-summary entries, and
    should not be treated as real test failures.
    """
    return bool(_PYTEST_FAILED_RE.match(line.strip()))


def _parse_failed_lines(failed_tests: List[str]) -> List[Finding]:
    """Turn pytest FAILED short-summary lines into structured findings.

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

    def cache_inputs(self, project_root: str) -> Optional[str]:
        """Scope the cache to Python files only.

        pytest only cares about .py files, so edits to YAML, Markdown,
        TOML, or other non-Python assets won't invalidate this check's
        cache.  Saves the full test-suite time (~15s) on runs where only
        docs or config changed.
        """
        from slopmop.core.cache import hash_file_scope

        return hash_file_scope(project_root, ["."], {".py"}, self.config)

    def _testmon_available(self, project_root: str) -> bool:
        """Return True if pytest-testmon is importable in the project venv.

        pytest-testmon enables dependency-aware test selection: on each
        run only tests whose source dependencies have changed are executed,
        skipping everything else.  The fast path activates automatically
        once .testmondata has been seeded (``pytest --testmon`` once).
        """
        try:
            probe = self._run_command(
                [
                    self.get_project_python(project_root),
                    "-c",
                    "import pytest_testmon",
                ],
                cwd=project_root,
                timeout=10,
            )
            return probe.returncode == 0
        except Exception:
            return False

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

        # Testmon fast path: skip coverage regeneration and only execute
        # tests whose source dependencies have changed since the last run.
        # Activates only when three conditions are met:
        #   1. pytest-testmon is installed in the project venv
        #   2. .testmondata exists (seeded by a prior `pytest --testmon` run)
        #   3. coverage.xml exists (from a prior full run, keeps it fresh)
        # To enable: run `pytest --testmon` once in the project root.
        # Note: --testmon and --cov conflict; fast-path skips coverage regen.
        testmon_available = self._testmon_available(project_root)
        use_testmon = (
            testmon_available
            and (Path(project_root) / ".testmondata").exists()
            and (Path(project_root) / "coverage.xml").exists()
        )

        if use_testmon:
            cmd = [
                self.get_project_python(project_root),
                "-m",
                "pytest",
                "--testmon",
                "-v",
                "--tb=short",
            ]
        else:
            cmd = [
                self.get_project_python(project_root),
                "-m",
                "pytest",
                "--cov=.",
                "--cov-report=xml:coverage.xml",
                "--cov-report=term-missing",
                "-v",
                "--tb=short",
            ]

        result = self._run_command(cmd, cwd=project_root, timeout=300)
        duration = time.time() - start_time
        return self._evaluate_pytest_result(result, duration, use_testmon)

    def _evaluate_pytest_result(
        self, result: SubprocessResult, duration: float, use_testmon: bool
    ) -> CheckResult:
        """Translate a pytest ``CommandResult`` into a ``CheckResult``."""
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
            return self._evaluate_pytest_failure(result, duration, use_testmon)

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output=result.output,
        )

    def _evaluate_pytest_failure(
        self, result: SubprocessResult, duration: float, use_testmon: bool
    ) -> CheckResult:
        """Handle a non-zero pytest exit code."""
        lines = result.output.split("\n")
        failed_tests = [line for line in lines if _is_failed_summary_line(line)]

        # pytest exit code 5 = "no tests were collected/run".
        # When testmon deselects every test (nothing in the changed
        # set has failing dependencies), this is a clean pass.
        if use_testmon and result.returncode == 5:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output="All tests passed (no changes detected by testmon).",
            )

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
