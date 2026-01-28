"""
Python coverage checks — global threshold and diff-cover.

Two checks in one module:
- PythonCoverageCheck: 80% global coverage threshold
- PythonDiffCoverageCheck: 80% coverage on changed files only
- PythonNewCodeCoverageCheck: CI-oriented new-code coverage gate
"""

import os
import sys
import time
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run

COVERAGE_THRESHOLD = 80
CI_BUFFER = 0.5  # CI environments get slight buffer for timing variance
COVERAGE_POLL_TIMEOUT = 10  # seconds to wait for coverage.xml (safety net)


def _wait_for_coverage_xml(path: str) -> bool:
    """Poll for coverage.xml to appear when running alongside python-tests.

    In parallel mode, python-tests may still be generating .coverage and
    coverage.xml when this check starts.  Wait up to COVERAGE_POLL_TIMEOUT
    seconds for the file to appear with non-zero size.
    """
    deadline = time.time() + COVERAGE_POLL_TIMEOUT
    while time.time() < deadline:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return True
        time.sleep(0.5)
    return False


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

        # In parallel runs, python-tests may still be generating coverage data.
        # Poll for coverage.xml (written after .coverage) to ensure data is ready.
        if not _wait_for_coverage_xml(coverage_file):
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


def _get_compare_branch() -> str:
    """Resolve the branch to diff against.

    Precedence: COMPARE_BRANCH env → GITHUB_BASE_REF (set in PR CI) → origin/main.
    """
    return (
        os.environ.get("COMPARE_BRANCH")
        or os.environ.get("GITHUB_BASE_REF")
        or "origin/main"
    )


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

        compare_branch = _get_compare_branch()

        cmd = [
            sys.executable,
            "-m",
            "diff_cover.diff_cover_script",
            "coverage.xml",
            f"--compare-branch={compare_branch}",
            f"--fail-under={COVERAGE_THRESHOLD}",
        ]
        result = run(cmd, cwd=working_dir)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output=f"Changed files have adequate coverage (vs {compare_branch})",
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
            fix_hint=f"Your changed files have <{COVERAGE_THRESHOLD}% coverage. "
            f"Add tests for the new code shown above.",
        )


class PythonNewCodeCoverageCheck(BaseCheck):
    """Coverage on new/changed code only — CI-oriented diff-cover gate.

    Semantically identical to PythonDiffCoverageCheck but registered
    under the ``python-new-code-coverage`` name that CI workflows
    reference when enforcing coverage on PRs.
    """

    @property
    def name(self) -> str:
        return "python-new-code-coverage"

    @property
    def description(self) -> str:
        return f"New-code coverage gate ({COVERAGE_THRESHOLD}%, CI-oriented)"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        base = working_dir or os.getcwd()
        coverage_file = os.path.join(base, "coverage.xml")

        if not os.path.exists(coverage_file):
            return self._make_result(
                status=CheckStatus.ERROR,
                output="coverage.xml not found. Run python-tests first to generate it.",
                fix_hint="Run: python setup.py --checks python-tests",
            )

        compare_branch = _get_compare_branch()

        cmd = [
            sys.executable,
            "-m",
            "diff_cover.diff_cover_script",
            "coverage.xml",
            f"--compare-branch={compare_branch}",
            f"--fail-under={COVERAGE_THRESHOLD}",
        ]
        result = run(cmd, cwd=working_dir)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output=f"New code coverage adequate (vs {compare_branch})",
            )

        if "No diff" in result.stdout or result.returncode == 0:
            return self._make_result(
                status=CheckStatus.PASSED,
                output="No changed files to check coverage on",
            )

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout or result.stderr,
            fix_hint=f"New code has <{COVERAGE_THRESHOLD}% coverage. "
            f"Add tests for the changed lines shown above.",
        )
