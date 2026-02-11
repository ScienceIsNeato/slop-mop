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
from slopmop.constants import NPM_INSTALL_FAILED
from slopmop.core.result import CheckResult, CheckStatus


class JavaScriptTypesCheck(BaseCheck, JavaScriptCheckMixin):
    """TypeScript type checking via tsc --noEmit.

    Wraps the TypeScript compiler in check-only mode. The --noEmit
    flag performs full type checking without producing output files,
    making it faster than a full build and safe to run in parallel.

    Profiles: javascript

    Configuration:
      tsconfig: "tsconfig.json" — path to tsconfig relative to
          project root. Falls back to tsconfig.ci.json if it exists
          and no explicit config is set.

    Common failures:
      TypeScript errors: Output shows each error with file, line,
          and error code (e.g., TS2322). Fix the type mismatches.
      Timeout: Type checking took > 3 minutes. This can happen
          with very large projects or circular type references.
      npm install failed: TypeScript must be in devDependencies.

    Re-validate:
      ./sm validate javascript:types --verbose
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
            npm_cmd = self._get_npm_install_command(project_root)
            npm_result = self._run_command(npm_cmd, cwd=project_root, timeout=120)
            if not npm_result.success:
                return self._create_result(
                    status=CheckStatus.ERROR,
                    duration=time.time() - start_time,
                    error=NPM_INSTALL_FAILED,
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
        cmd: List[str] = ["npx", "tsc", "--noEmit", "-p", tsconfig]

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
            error_lines = [line for line in lines if "error TS" in line]
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
