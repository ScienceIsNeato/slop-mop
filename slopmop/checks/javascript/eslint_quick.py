"""Quick frontend validation check.

Runs ESLint in errors-only mode for rapid feedback (~5s) on
frontend JavaScript sources. Requires 'frontend_dirs' in .sb_config.json.
"""

import os
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
from slopmop.core.result import CheckResult, CheckStatus


class FrontendCheck(BaseCheck, JavaScriptCheckMixin):
    """Quick frontend JavaScript validation.

    Wraps ESLint in errors-only (--quiet) mode for rapid feedback
    (~5s) on frontend JavaScript source directories. Only checks
    for critical errors (no-undef, no-unused-vars) rather than
    full lint.

    Profiles: javascript

    Configuration:
      frontend_dirs: [] (required) — directories containing
          frontend JS (e.g., ["static", "frontend", "public"]).
          Must be configured in .sb_config.json. Gate skips if
          no directories are configured.

    Common failures:
      ESLint errors: Run `npx eslint --fix <file>` to auto-fix
          fixable issues. Review remaining errors manually.
      ESLint config error: Check .eslintrc or eslint.config.js
          for syntax errors.

    Re-validate:
      ./sm validate laziness:js-frontend --verbose
    """

    tool_context = ToolContext.NODE

    @property
    def name(self) -> str:
        return "js-frontend"

    @property
    def display_name(self) -> str:
        return "⚡ Frontend Check (quick ESLint)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.LAZINESS

    @property
    def flaw(self) -> Flaw:
        return Flaw.LAZINESS

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="frontend_dirs",
                field_type="string[]",
                default=[],
                description="Directories containing frontend JavaScript",
                required=True,
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        if not self.is_javascript_project(project_root):
            return False
        # Only applicable if frontend_dirs is configured
        return bool(self._get_configured_dirs(project_root))

    def _get_configured_dirs(self, project_root: str) -> List[str]:
        """Get frontend directories from config.

        Returns only directories that exist in the project.
        """
        configured = self.config.get("frontend_dirs", [])
        return [d for d in configured if os.path.isdir(os.path.join(project_root, d))]

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()

        js_dirs = self._get_configured_dirs(project_root)
        if not js_dirs:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="No frontend_dirs configured in .sb_config.json.",
                fix_suggestion='Add "frontend_dirs": ["static", "public"] to .sb_config.json',
            )

        # Run ESLint in errors-only mode (fast path)
        cmd = [
            "npx",
            "eslint",
            "--ext",
            ".js",
            "--rule",
            '{"no-undef": "error", "no-unused-vars": "warn"}',
            "--quiet",  # errors only
        ] + js_dirs

        result = self._run_command(cmd, cwd=project_root, timeout=30)
        duration = time.time() - start_time

        if result.success:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"Frontend check passed ({', '.join(js_dirs)})",
            )

        if result.returncode == 2:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="ESLint configuration error",
                output=result.output,
                fix_suggestion="Check .eslintrc or eslint.config.js for syntax errors.",
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=result.output,
            error="ESLint errors found",
            fix_suggestion="Fix ESLint errors above. Run: npx eslint --fix <file>",
        )
