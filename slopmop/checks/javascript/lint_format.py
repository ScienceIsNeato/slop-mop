"""JavaScript lint and format check using ESLint and Prettier."""

import time
from typing import List, Optional

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    Flaw,
    GateCategory,
    JavaScriptCheckMixin,
)
from slopmop.constants import NPM_INSTALL_FAILED
from slopmop.core.result import CheckResult, CheckStatus


class JavaScriptLintFormatCheck(BaseCheck, JavaScriptCheckMixin):
    """JavaScript/TypeScript lint and format enforcement.

    Wraps ESLint and Prettier. Auto-fix runs ESLint --fix and
    Prettier --write before checking. Installs npm dependencies
    automatically if node_modules/ is missing.

    Profiles: commit, pr

    Configuration:
      Uses project's .eslintrc and .prettierrc. No additional
      sm-specific config — respects your existing tool configs.

    Common failures:
      ESLint errors: Run `npx eslint . --fix` to auto-fix.
          Remaining errors need manual code changes.
      Prettier drift: Run `npx prettier --write .` to reformat.
      npm install failed: Check package.json for syntax errors
          or missing registry access.

    Re-validate:
      ./sm validate javascript:lint-format --verbose
    """

    @property
    def name(self) -> str:
        return "lint-format"

    @property
    def display_name(self) -> str:
        return "🎨 Lint & Format (ESLint, Prettier)"

    @property
    def category(self) -> GateCategory:
        return GateCategory.JAVASCRIPT

    @property
    def flaw(self) -> Flaw:
        return Flaw.LAZINESS

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="npm_install_flags",
                field_type="string[]",
                default=[],
                description=(
                    "Additional flags for npm install (e.g., ['--legacy-peer-deps']). "
                    "Also checks .npmrc for legacy-peer-deps=true."
                ),
                required=False,
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        return self.is_javascript_project(project_root)

    def skip_reason(self, project_root: str) -> str:
        return "No package.json found (not a JavaScript/TypeScript project)"

    def can_auto_fix(self) -> bool:
        return True

    def auto_fix(self, project_root: str) -> bool:
        """Auto-fix formatting issues."""
        fixed = False

        # Install deps if needed
        if not self.has_node_modules(project_root):
            npm_cmd = self._get_npm_install_command(project_root)
            self._run_command(npm_cmd, cwd=project_root, timeout=120)

        # Run ESLint fix
        result = self._run_command(
            ["npx", "eslint", ".", "--fix"],
            cwd=project_root,
            timeout=60,
        )
        if result.success:
            fixed = True

        # Run Prettier
        result = self._run_command(
            ["npx", "prettier", "--write", "."],
            cwd=project_root,
            timeout=60,
        )
        if result.success:
            fixed = True

        return fixed

    def run(self, project_root: str) -> CheckResult:
        """Run lint and format checks."""
        start_time = time.time()
        issues: List[str] = []
        output_parts: List[str] = []

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

        # Check ESLint
        eslint_result = self._check_eslint(project_root)
        if eslint_result:
            issues.append(eslint_result)
            output_parts.append(f"ESLint: {eslint_result}")
        else:
            output_parts.append("ESLint: ✅ No lint errors")

        # Check Prettier
        prettier_result = self._check_prettier(project_root)
        if prettier_result:
            issues.append(prettier_result)
            output_parts.append(f"Prettier: {prettier_result}")
        else:
            output_parts.append("Prettier: ✅ Formatting OK")

        duration = time.time() - start_time

        if issues:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output="\n".join(output_parts),
                error=f"{len(issues)} issue(s) found",
                fix_suggestion="Run: npx eslint . --fix && npx prettier --write .",
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output="\n".join(output_parts),
        )

    def _check_eslint(self, project_root: str) -> Optional[str]:
        """Check ESLint."""
        result = self._run_command(
            ["npx", "eslint", "."],
            cwd=project_root,
            timeout=60,
        )

        if not result.success and result.output.strip():
            lines = result.output.strip().split("\n")
            return f"{len(lines)} lint issue(s)"
        return None

    def _check_prettier(self, project_root: str) -> Optional[str]:
        """Check Prettier formatting."""
        result = self._run_command(
            ["npx", "prettier", "--check", "."],
            cwd=project_root,
            timeout=60,
        )

        if not result.success:
            return "Formatting issues found"
        return None
