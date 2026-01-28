"""
JavaScript test runner — Jest via npm.
"""

from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run


class JSTestsCheck(BaseCheck):
    """Jest test runner for JavaScript."""

    @property
    def name(self) -> str:
        return "js-tests"

    @property
    def description(self) -> str:
        return "JavaScript tests via Jest (npm run test)"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        import os

        base = working_dir or os.getcwd()
        package_json = os.path.join(base, "package.json")

        if not os.path.exists(package_json):
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No package.json found — no JS tests to run.",
            )

        cmd = ["npm", "test"]
        result = run(cmd, cwd=working_dir, timeout=120)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output=self._extract_summary(result.stdout + result.stderr),
            )

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout + result.stderr,
            fix_hint="Fix failing JavaScript tests. Run: npm test -- --verbose for details.",
        )

    def _extract_summary(self, output: str) -> str:
        for line in reversed(output.splitlines()):
            if "Tests:" in line or "Test Suites:" in line:
                return line.strip()
        return "JS tests completed"
