"""Quick frontend validation check.

Runs ESLint in errors-only mode for rapid feedback (~5s) on
frontend JavaScript sources. Requires 'frontend_dirs' in .sb_config.json.
"""

import os
import re
import time
from typing import List

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    ToolContext,
)
from slopmop.checks.mixins import JavaScriptCheckMixin
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

# ESLint stylish format detail line:  line:col  error|warning  message  rule-id
_ESLINT_STYLISH_RE = re.compile(
    r"^\s+(\d+):(\d+)\s+(error|warning)\s+(.+?)\s{2,}(\S+)\s*$"
)


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
      sm swab -g laziness:sloppy-frontend.js --verbose
    """

    tool_context = ToolContext.NODE
    role = CheckRole.FOUNDATION  # eslint (errors-only)

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

        findings = self._parse_stylish(result.output, project_root)
        msg = "ESLint errors found"
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=result.output,
            error=msg,
            fix_suggestion="Fix ESLint errors above. Run: npx eslint --fix <file>",
            findings=findings or [Finding(message=msg, level=FindingLevel.ERROR)],
        )

    @staticmethod
    def _parse_stylish(output: str, project_root: str) -> List[Finding]:
        """Parse ESLint stylish output into Findings.

        Stylish format: unindented absolute file path on its own line,
        followed by indented ``line:col  severity  message  rule`` lines.
        """
        findings: List[Finding] = []
        current_file = ""
        for line in output.splitlines():
            if not line.strip():
                continue
            m = _ESLINT_STYLISH_RE.match(line)
            if m is None and not line[0].isspace():
                # Unindented non-empty line → file header
                path = line.strip()
                if path.startswith(project_root):
                    path = os.path.relpath(path, project_root)
                current_file = path
                continue
            if m and current_file:
                findings.append(
                    Finding(
                        message=m.group(4).strip(),
                        level=(
                            FindingLevel.ERROR
                            if m.group(3) == "error"
                            else FindingLevel.WARNING
                        ),
                        file=current_file,
                        line=int(m.group(1)),
                        column=int(m.group(2)),
                        rule_id=m.group(5),
                    )
                )
        return findings
