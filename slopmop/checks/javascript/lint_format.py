"""JavaScript lint and format check using ESLint and Prettier."""

import json
import os
import time
from typing import List, Optional, Tuple

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    ToolContext,
)
from slopmop.checks.mixins import JavaScriptCheckMixin
from slopmop.constants import NPM_INSTALL_FAILED
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel


class JavaScriptLintFormatCheck(BaseCheck, JavaScriptCheckMixin):
    """JavaScript/TypeScript lint and format enforcement.

    Wraps ESLint and Prettier. Auto-fix runs ESLint --fix and
    Prettier --write before checking. Installs npm dependencies
    automatically if node_modules/ is missing.

    Level: swab

    Configuration:
      Uses project's .eslintrc and .prettierrc. No additional
      sm-specific config — respects your existing tool configs.

    Common failures:
      ESLint errors: Run `npx eslint . --fix` to auto-fix.
          Remaining errors need manual code changes.
      Prettier drift: Run `npx prettier --write .` to reformat.
      npm install failed: Check package.json for syntax errors
          or missing registry access.

    Re-check:
      sm swab -g laziness:sloppy-formatting.js --verbose
    """

    tool_context = ToolContext.NODE
    role = CheckRole.FOUNDATION  # eslint, prettier

    @property
    def name(self) -> str:
        return "sloppy-formatting.js"

    @property
    def display_name(self) -> str:
        return "🎨 Lint & Format (ESLint, Prettier)"

    @property
    def gate_description(self) -> str:
        return "🎨 ESLint + Prettier (supports auto-fix 🔧)"

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
        eslint_result, eslint_findings = self._check_eslint(project_root)
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
            msg = f"{len(issues)} issue(s) found"
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output="\n".join(output_parts),
                error=msg,
                fix_suggestion="Run: npx eslint . --fix && npx prettier --write .",
                findings=eslint_findings
                or [Finding(message=msg, level=FindingLevel.ERROR)],
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output="\n".join(output_parts),
        )

    def _check_eslint(self, project_root: str) -> Tuple[Optional[str], List[Finding]]:
        """Check ESLint."""
        result = self._run_command(
            ["npx", "eslint", ".", "--format", "json"],
            cwd=project_root,
            timeout=60,
        )

        if not result.success and result.output.strip():
            findings: List[Finding] = []
            try:
                data = json.loads(result.stdout)
                for file_result in data:
                    filepath = file_result.get("filePath", "")
                    if filepath.startswith(project_root):
                        filepath = os.path.relpath(filepath, project_root)
                    for msg in file_result.get("messages", []):
                        findings.append(
                            Finding(
                                message=msg.get("message", ""),
                                level=(
                                    FindingLevel.ERROR
                                    if msg.get("severity") == 2
                                    else FindingLevel.WARNING
                                ),
                                file=filepath,
                                line=msg.get("line"),
                                column=msg.get("column"),
                                rule_id=msg.get("ruleId"),
                            )
                        )
            except (json.JSONDecodeError, TypeError):
                pass
            count = (
                len(findings) if findings else len(result.output.strip().split("\n"))
            )
            return f"{count} lint issue(s)", findings
        return None, []

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
