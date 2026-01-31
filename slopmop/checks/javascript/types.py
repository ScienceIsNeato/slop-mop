"""TypeScript type checking gate."""

import time
from typing import List

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    GateCategory,
    JavaScriptCheckMixin,
)
from slopmop.core.result import CheckResult, CheckStatus


class JavaScriptTypesCheck(BaseCheck, JavaScriptCheckMixin):
    """TypeScript type checking gate.

    Runs the TypeScript compiler (tsc) in noEmit mode to check for type errors.
    """

    @property
    def name(self) -> str:
        return "types"

    @property
    def display_name(self) -> str:
        return "🏗️ TypeScript Types (tsc)"

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
                name="type_check_command",
                field_type="string",
                default="npx tsc --noEmit",
                description="Command to run TypeScript type checking",
            ),
            ConfigField(
                name="tsconfig",
                field_type="string",
                default="tsconfig.json",
                description="Path to tsconfig.json (relative to project root)",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Check if this is a TypeScript project."""
        import os

        # Check for tsconfig.json
        tsconfig_path = os.path.join(project_root, "tsconfig.json")
        if os.path.exists(tsconfig_path):
            return True

        # Also check for tsconfig.ci.json (common in CI environments)
        tsconfig_ci_path = os.path.join(project_root, "tsconfig.ci.json")
        if os.path.exists(tsconfig_ci_path):
            return True

        return False

    def run(self, project_root: str) -> CheckResult:
        """Run TypeScript type checking."""
        import os

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

        # Get the tsconfig to use
        tsconfig = self.config.get("tsconfig", "tsconfig.json")

        # Check for CI-specific tsconfig
        tsconfig_ci_path = os.path.join(project_root, "tsconfig.ci.json")
        if os.path.exists(tsconfig_ci_path):
            tsconfig = "tsconfig.ci.json"

        # Build the type check command
        cmd = ["npx", "tsc", "--noEmit", "-p", tsconfig]

        result = self._run_command(
            cmd,
            cwd=project_root,
            timeout=180,  # 3 minutes
        )

        duration = time.time() - start_time

        if result.timed_out:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error="Type checking timed out after 3 minutes",
            )

        if not result.success:
            # Parse error count from output
            lines = result.output.split("\n")
            error_lines = [l for l in lines if "error TS" in l]
            error_count = len(error_lines)

            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error=f"{error_count} TypeScript error(s) found",
                fix_suggestion="Run: npx tsc --noEmit to see detailed errors",
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output=result.output,
        )
