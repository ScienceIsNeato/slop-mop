"""TypeScript type checking gate.

This gate runs the TypeScript compiler (tsc) with the --noEmit flag to perform
static type analysis without generating any JavaScript output files.

Why --noEmit?
-------------
The --noEmit flag tells TypeScript to:
1. Parse all TypeScript/JavaScript files according to tsconfig.json
2. Perform full type checking and report any type errors
3. NOT write any output files (.js, .d.ts, .js.map)

This is ideal for CI/pre-commit checks because:
- It's faster than a full build (no file I/O for outputs)
- It validates types without side effects
- It works alongside other build tools (Webpack, Vite, etc.)

The check respects tsconfig.json settings including:
- strict mode options
- path aliases
- include/exclude patterns
- compiler options

See: https://www.typescriptlang.org/tsconfig#noEmit
"""

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

    Runs the TypeScript compiler (tsc) with --noEmit to check for type errors
    without producing output files. This is the standard approach for CI/CD
    type validation in TypeScript projects.

    The --noEmit flag means:
    - Full type checking is performed
    - No .js, .d.ts, or .map files are written
    - Faster execution than a full build
    - Safe to run in parallel with other build processes
    """

    @property
    def name(self) -> str:
        return "types"

    @property
    def display_name(self) -> str:
        return "🏗️ TypeScript Types (tsc --noEmit)"

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
                name="tsconfig",
                field_type="string",
                default="tsconfig.json",
                description="Path to tsconfig.json (relative to project root)",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Check if this is a TypeScript project."""
        import os

        # First, check if user has configured a specific tsconfig
        configured_tsconfig = self.config.get("tsconfig", "tsconfig.json")
        configured_path = os.path.join(project_root, configured_tsconfig)
        if os.path.exists(configured_path):
            return True

        # Check for standard tsconfig.json
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

        # Get the tsconfig to use - respect user config, fallback to CI config if no user config
        user_tsconfig = self.config.get("tsconfig")
        default_tsconfig = "tsconfig.json"

        if user_tsconfig and user_tsconfig != default_tsconfig:
            # User explicitly configured a specific tsconfig - use it
            tsconfig = user_tsconfig
        else:
            # No explicit user config - check for CI-specific tsconfig as fallback
            tsconfig_ci_path = os.path.join(project_root, "tsconfig.ci.json")
            if os.path.exists(tsconfig_ci_path):
                tsconfig = "tsconfig.ci.json"
            else:
                tsconfig = default_tsconfig

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
                fix_suggestion=f"Run: npx tsc --noEmit -p {tsconfig} to see detailed errors",
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output=result.output,
        )
