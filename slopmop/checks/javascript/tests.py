"""JavaScript test execution check using Jest."""

import time
from typing import List

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    GateCategory,
    JavaScriptCheckMixin,
)
from slopmop.core.result import CheckResult, CheckStatus


class JavaScriptTestsCheck(BaseCheck, JavaScriptCheckMixin):
    """JavaScript test execution check.

    Runs Jest to execute JavaScript tests.
    """

    @property
    def name(self) -> str:
        return "tests"

    @property
    def display_name(self) -> str:
        return "🧪 Tests (Jest)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.JAVASCRIPT

    @property
    def depends_on(self) -> List[str]:
        return ["javascript:lint-format"]

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="test_command",
                field_type="string",
                default="npm test",
                description="Command to run tests",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        return self.is_javascript_project(project_root)

    def run(self, project_root: str) -> CheckResult:
        """Run Jest tests."""
        start_time = time.time()

        # Install deps if needed
        if not self.has_node_modules(project_root):
            npm_result = self._run_command(
                ["npm", "install"], cwd=project_root, timeout=120
            )
            if not npm_result.success:
                return self._create_result(
                    status=CheckStatus.ERROR,
                    duration=time.time() - start_time,
                    error="npm install failed",
                    output=npm_result.output,
                )

        # Run Jest
        result = self._run_command(
            ["npx", "jest", "--coverage", "--passWithNoTests"],
            cwd=project_root,
            timeout=300,
        )

        duration = time.time() - start_time

        if result.timed_out:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error="Tests timed out after 5 minutes",
            )

        if not result.success:
            # Parse failure info
            lines = result.output.split("\n")
            failed = [line for line in lines if "FAIL" in line]

            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error=f"{len(failed)} test file(s) failed",
                fix_suggestion="Run: npm test to see detailed failures",
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output=result.output,
        )
