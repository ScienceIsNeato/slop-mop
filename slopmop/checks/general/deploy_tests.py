"""Deploy App shell script test gate.

Validates the deploy_app.sh script by running its unit tests.
This ensures the deployment script works correctly before using it.
"""

import os
import time
from typing import List

from slopmop.checks.base import BaseCheck, ConfigField, GateCategory
from slopmop.core.result import CheckResult, CheckStatus


class DeployScriptTestsCheck(BaseCheck):
    """Deploy script unit tests gate.

    Runs the unit tests for deploy_app.sh to validate:
    - Argument parsing works correctly
    - Dry-run mode functions without side effects
    - Actionable output is generated
    - Decision logic (skip steps when appropriate)

    The tests use --dry-run mode so no actual deployments happen.
    """

    @property
    def name(self) -> str:
        return "deploy-tests"

    @property
    def display_name(self) -> str:
        return "🚀 Deploy Script Tests"

    @property
    def category(self) -> GateCategory:
        return GateCategory.GENERAL

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="test_script",
                field_type="string",
                default="scripts/__tests__/deploy_app.test.sh",
                description="Path to deploy script test file",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Check if this project has the deploy script and tests."""
        deploy_script = os.path.join(project_root, "scripts", "deploy_app.sh")
        test_script = os.path.join(
            project_root,
            self.config.get("test_script", "scripts/__tests__/deploy_app.test.sh"),
        )
        return os.path.exists(deploy_script) and os.path.exists(test_script)

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping - no deploy scripts found."""
        deploy_script = os.path.join(project_root, "scripts", "deploy_app.sh")
        test_script = self.config.get(
            "test_script", "scripts/__tests__/deploy_app.test.sh"
        )
        if not os.path.exists(deploy_script):
            return "No deploy script found at scripts/deploy_app.sh"
        return f"No deploy test script found at {test_script}"

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()

        test_script = self.config.get(
            "test_script", "scripts/__tests__/deploy_app.test.sh"
        )
        test_path = os.path.join(project_root, test_script)

        if not os.path.exists(test_path):
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output=f"Test script not found: {test_script}",
                fix_suggestion="Create scripts/__tests__/deploy_app.test.sh",
            )

        # Run the shell test script
        cmd = ["/bin/bash", test_path]
        result = self._run_command(cmd, cwd=project_root, timeout=120)
        duration = time.time() - start_time

        if result.success:
            # Extract test summary from output
            lines = result.stdout.strip().split("\n")
            summary_lines = [
                line
                for line in lines
                if "Passed:" in line or "Failed:" in line or "Total:" in line
            ]
            summary = "\n".join(summary_lines) if summary_lines else "All tests passed"

            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"Deploy script tests passed.\n{summary}",
            )
        else:
            # Extract failure info
            output = result.stdout or result.stderr or "Unknown error"

            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=output,
                error="Deploy script tests failed",
                fix_suggestion="Check the test output above for specific failures. "
                "Run: ./scripts/__tests__/deploy_app.test.sh to debug locally.",
            )
