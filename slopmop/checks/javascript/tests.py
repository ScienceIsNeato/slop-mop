"""JavaScript test execution check using Jest."""

import time
from typing import List

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    Flaw,
    GateCategory,
    JavaScriptCheckMixin,
    ToolContext,
)
from slopmop.constants import NPM_INSTALL_FAILED
from slopmop.core.result import CheckResult, CheckStatus


class JavaScriptTestsCheck(BaseCheck, JavaScriptCheckMixin):
    """JavaScript test execution via Jest.

    Wraps Jest with --coverage and --passWithNoTests. Installs
    npm dependencies automatically if missing.

    Profiles: commit, pr

    Configuration:
      test_command: "npm test" — command to run tests. Override
          if your project uses a custom test script.

    Common failures:
      Test failures: Output shows FAIL lines. Run `npm test` for
          full details.
      Timeout: Suite took > 5 minutes. Look for missing mocks
          or slow async operations.
      npm install failed: Check package.json syntax.

    Re-check:
      ./sm swab -g overconfidence:js-tests --verbose
    """

    tool_context = ToolContext.NODE

    @property
    def name(self) -> str:
        return "js-tests"

    @property
    def display_name(self) -> str:
        return "🧪 Tests (Jest)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

    @property
    def depends_on(self) -> List[str]:
        return ["laziness:js-lint"]

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

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping — delegate to JavaScriptCheckMixin."""
        return JavaScriptCheckMixin.skip_reason(self, project_root)

    def is_applicable(self, project_root: str) -> bool:
        return self.is_javascript_project(project_root)

    def run(self, project_root: str) -> CheckResult:
        """Run Jest tests."""
        start_time = time.time()

        # Install deps if needed
        if not self.has_node_modules(project_root):
            npm_cmd = self._get_npm_install_command(project_root)
            npm_result = self._run_command(npm_cmd, cwd=project_root, timeout=120)
            if not npm_result.success:
                return self._create_result(
                    status=CheckStatus.ERROR,
                    duration=time.time() - start_time,
                    error=NPM_INSTALL_FAILED,
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
