"""JavaScript lint and format check using ESLint and Prettier."""

import time
from typing import List, Optional

from slopbucket.checks.base import BaseCheck, JavaScriptCheckMixin
from slopbucket.core.result import CheckResult, CheckStatus


class JavaScriptLintFormatCheck(BaseCheck, JavaScriptCheckMixin):
    """JavaScript lint and format check.

    Runs:
    - ESLint: Linting
    - Prettier: Formatting

    Auto-fix is enabled by default.
    """

    @property
    def name(self) -> str:
        return "js-lint-format"

    @property
    def display_name(self) -> str:
        return "🎨 JavaScript Lint & Format (ESLint, Prettier)"

    def is_applicable(self, project_root: str) -> bool:
        return self.is_javascript_project(project_root)

    def can_auto_fix(self) -> bool:
        return True

    def auto_fix(self, project_root: str) -> bool:
        """Auto-fix formatting issues."""
        fixed = False

        # Install deps if needed
        if not self.has_node_modules(project_root):
            self._run_command(["npm", "install"], cwd=project_root, timeout=120)

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
