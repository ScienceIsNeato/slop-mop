"""JavaScript test execution check using Jest."""

import time
from typing import List

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    Flaw,
    GateCategory,
    ToolContext,
)
from slopmop.checks.constants import TESTS_TIMED_OUT_MSG
from slopmop.checks.mixins import JavaScriptCheckMixin
from slopmop.constants import NPM_INSTALL_FAILED
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel


class JavaScriptTestsCheck(BaseCheck, JavaScriptCheckMixin):
    """JavaScript test execution via Jest.

    Wraps Jest with --coverage and --passWithNoTests. Installs
    npm dependencies automatically if missing.

    Level: swab

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
      ./sm swab -g overconfidence:untested-code.js --verbose
    """

    tool_context = ToolContext.NODE

    @property
    def name(self) -> str:
        return "untested-code.js"

    @property
    def display_name(self) -> str:
        return "🧪 Tests (Jest)"

    @property
    def gate_description(self) -> str:
        return "🧪 Jest test execution"

    @property
    def category(self) -> GateCategory:
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

    @property
    def depends_on(self) -> List[str]:
        return ["laziness:sloppy-formatting.js"]

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
                error=TESTS_TIMED_OUT_MSG,
                findings=[
                    Finding(message=TESTS_TIMED_OUT_MSG, level=FindingLevel.ERROR)
                ],
            )

        if not result.success:
            # Jest's text reporter prefixes each failing suite with
            # ``FAIL  <path>`` (two spaces).  Extract file paths for
            # SARIF — file-level findings, no line numbers, since a
            # failing test file is a file-level problem.
            findings: List[Finding] = []
            for line in result.output.split("\n"):
                stripped = line.strip()
                if stripped.startswith("FAIL "):
                    # ``FAIL  js-tests/calc.test.js`` → second token
                    parts = stripped.split(None, 1)
                    if len(parts) == 2:
                        findings.append(
                            Finding(message="Test suite failed", file=parts[1])
                        )

            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error=f"{len(findings)} test file(s) failed",
                fix_suggestion="Run: npm test to see detailed failures",
                findings=findings,
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output=result.output,
        )
