"""
JavaScript coverage check — Jest coverage thresholds.
"""

from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run

JS_COVERAGE_THRESHOLD = 80


class JSCoverageCheck(BaseCheck):
    """Jest coverage threshold enforcement."""

    @property
    def name(self) -> str:
        return "js-coverage"

    @property
    def description(self) -> str:
        return f"JavaScript coverage threshold ({JS_COVERAGE_THRESHOLD}% lines)"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        import os

        base = working_dir or os.getcwd()
        if not os.path.exists(os.path.join(base, "package.json")):
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No package.json — no JS coverage to check.",
            )

        cmd = ["npm", "run", "test:coverage"]
        result = run(cmd, cwd=working_dir, timeout=120)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output=self._extract_coverage(result.stdout + result.stderr),
            )

        output = result.stdout + result.stderr
        return self._make_result(
            status=CheckStatus.FAILED,
            output=output,
            fix_hint=f"JS coverage below {JS_COVERAGE_THRESHOLD}%. Add tests for uncovered code paths.",
        )

    def _extract_coverage(self, output: str) -> str:
        for line in output.splitlines():
            if "All files" in line or "%" in line:
                return line.strip()
        return "JS coverage check passed"
