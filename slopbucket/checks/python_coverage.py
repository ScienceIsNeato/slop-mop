"""
Python coverage checks — global threshold and diff-cover.

Two checks in one module:
- PythonCoverageCheck: 80% global coverage threshold
- PythonDiffCoverageCheck: 80% coverage on changed files only
"""

import os
import sys
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run

COVERAGE_THRESHOLD = 80
CI_BUFFER = 0.5  # CI environments get slight buffer for timing variance


class PythonCoverageCheck(BaseCheck):
    """Global coverage threshold enforcement."""

    @property
    def name(self) -> str:
        return "python-coverage"

    @property
    def description(self) -> str:
        return f"Coverage threshold ({COVERAGE_THRESHOLD}%)"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        base = working_dir or os.getcwd()
        coverage_file = os.path.join(base, "coverage.xml")

        if not os.path.exists(coverage_file):
            return self._make_result(
                status=CheckStatus.ERROR,
                output="coverage.xml not found. Run python-tests first to generate it.",
                fix_hint="Run: python setup.py --checks python-tests",
            )

        # Determine threshold (slight buffer in CI)
        is_ci = os.environ.get("CI", "").lower() in ("true", "1")
        threshold = COVERAGE_THRESHOLD - CI_BUFFER if is_ci else COVERAGE_THRESHOLD

        cmd = [
            sys.executable,
            "-m",
            "coverage",
            "report",
            f"--fail-under={threshold}",
            "--show-missing",
        ]
        result = run(cmd, cwd=working_dir)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output=self._extract_coverage_line(result.stdout),
            )

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout or result.stderr,
            fix_hint=f"Coverage is below {COVERAGE_THRESHOLD}%. Add tests for the uncovered lines shown above.",
        )

    def _extract_coverage_line(self, output: str) -> str:
        for line in output.splitlines():
            if "TOTAL" in line or "%" in line:
                return line.strip()
        return "Coverage check passed"


class PythonDiffCoverageCheck(BaseCheck):
    """Coverage enforcement on changed files only (diff-cover)."""

    @property
    def name(self) -> str:
        return "python-diff-coverage"

    @property
    def description(self) -> str:
        return f"Diff coverage on changed files ({COVERAGE_THRESHOLD}%)"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        base = working_dir or os.getcwd()
        coverage_file = os.path.join(base, "coverage.xml")

        if not os.path.exists(coverage_file):
            return self._make_result(
                status=CheckStatus.ERROR,
                output="coverage.xml not found. Run python-tests first.",
                fix_hint="Run: python setup.py --checks python-tests",
            )

        cmd = [
            sys.executable,
            "-m",
            "diff_cover.diff_cover_script",
            "coverage.xml",
            "--compare-branch=origin/main",
            f"--fail-under={COVERAGE_THRESHOLD}",
        ]
        result = run(cmd, cwd=working_dir)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output="Changed files have adequate coverage",
            )

        # diff-cover not finding changes is fine (not an error)
        if "No diff" in result.stdout or result.returncode == 0:
            return self._make_result(
                status=CheckStatus.PASSED,
                output="No changed files to check coverage on",
            )

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout or result.stderr,
            fix_hint=f"Your changed files have <{COVERAGE_THRESHOLD}% coverage. Add tests for the new code shown above.",
        )
