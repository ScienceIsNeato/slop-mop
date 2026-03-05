"""Quick frontend validation check.

Runs ESLint in errors-only mode for rapid feedback (~5s) on
frontend JavaScript sources. Requires 'frontend_dirs' in .sb_config.json.
"""

import json
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
from slopmop.core.result import CheckResult, CheckStatus, Finding


class FrontendCheck(BaseCheck, JavaScriptCheckMixin):
    """Quick frontend JavaScript validation.

    Wraps ESLint in errors-only (--quiet) mode for rapid feedback
    (~5s) on frontend JavaScript source directories. Only checks
    for critical errors (no-undef, no-unused-vars) rather than
    full lint.

    Level: swab

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

    Re-check:
      ./sm swab -g laziness:sloppy-frontend.js --verbose
    """

    tool_context = ToolContext.NODE

    @property
    def name(self) -> str:
        return "sloppy-frontend.js"

    @property
    def display_name(self) -> str:
        return "⚡ Frontend Check (quick ESLint)"

    @property
    def gate_description(self) -> str:
        return "⚡ Quick ESLint frontend check"

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

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping."""
        if not self.is_javascript_project(project_root):
            return JavaScriptCheckMixin.skip_reason(self, project_root)
        return "No frontend_dirs configured in .sb_config.json"

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

        # Run ESLint in errors-only mode (fast path).  --format json
        # gives us the same structured output eslint_expect.py parses —
        # file, line, column, rule per finding — at no extra runtime cost.
        cmd = [
            "npx",
            "eslint",
            "--ext",
            ".js",
            "--rule",
            '{"no-undef": "error", "no-unused-vars": "warn"}',
            "--quiet",  # errors only
            "--format",
            "json",
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

        # Parse ESLint JSON into Findings.  If parsing fails (output
        # corrupted, mixed stdout/stderr) the except branch emits a
        # single project-level finding — SARIF still has something to show.
        findings: List[Finding] = []
        try:
            for file_result in json.loads(result.stdout):
                filepath = file_result.get("filePath", "")
                if filepath.startswith(project_root):
                    filepath = os.path.relpath(filepath, project_root)
                for msg in file_result.get("messages", []):
                    findings.append(
                        Finding(
                            message=msg.get("message", "lint error"),
                            file=filepath or None,
                            line=msg.get("line") or None,
                            column=msg.get("column") or None,
                            rule_id=msg.get("ruleId") or None,
                        )
                    )
        except (json.JSONDecodeError, TypeError):
            findings = [Finding(message=f"ESLint: {result.output.strip()[:200]}")]

        # No explicit output= — the _create_result rail joins findings
        # into ``file:line:col: message`` lines.  Passing result.output
        # here would dump raw ESLint JSON into the console.
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            error=f"{len(findings)} ESLint error(s)",
            fix_suggestion="Fix ESLint errors above. Run: npx eslint --fix <file>",
            findings=findings,
        )
