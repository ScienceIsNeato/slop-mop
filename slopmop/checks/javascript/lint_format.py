"""JavaScript lint and format check using ESLint and Prettier."""

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
from slopmop.constants import NPM_INSTALL_FAILED
from slopmop.core.result import CheckResult, CheckStatus, Finding


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
      ./sm swab -g laziness:sloppy-formatting.js --verbose
    """

    tool_context = ToolContext.NODE

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

        eslint_findings = self._check_eslint(project_root)
        prettier_findings = self._check_prettier(project_root)
        findings = eslint_findings + prettier_findings

        output_parts = [
            (
                f"ESLint: {len(eslint_findings)} issue(s)"
                if eslint_findings
                else "ESLint: ✅ No lint errors"
            ),
            (
                f"Prettier: {len(prettier_findings)} file(s) need formatting"
                if prettier_findings
                else "Prettier: ✅ Formatting OK"
            ),
        ]

        duration = time.time() - start_time

        if findings:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output="\n".join(output_parts),
                error=f"{len(findings)} issue(s) found",
                fix_suggestion="Run: npx eslint . --fix && npx prettier --write .",
                findings=findings,
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output="\n".join(output_parts),
        )

    def _check_eslint(self, project_root: str) -> List[Finding]:
        """Run ESLint with ``--format json`` and extract per-line findings.

        ESLint's JSON format is a list of ``{filePath, messages[]}`` where
        each message has ``{ruleId, line, column, message, severity}``.
        Severity 2 = error, 1 = warning.  We surface both — a warning in
        lint config is still a finding the developer asked to be told about.
        """
        result = self._run_command(
            ["npx", "eslint", ".", "--format", "json"],
            cwd=project_root,
            timeout=60,
        )

        # Exit 0 with valid JSON means no findings; exit 0 with no output
        # means ESLint found nothing to lint.  Either way, clean.
        if result.success:
            return []

        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            # ESLint crashed, bad config, or something wrote to stdout
            # that isn't JSON.  Fall back to a single project-level
            # finding so SARIF still points somewhere useful.
            return [Finding(message=f"ESLint: {result.output.strip()[:200]}")]

        findings: List[Finding] = []
        for file_result in data:
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
        return findings

    def _check_prettier(self, project_root: str) -> List[Finding]:
        """Run ``prettier --check`` and extract files that need formatting.

        Prettier's check output lists unformatted files as ``[warn] path``
        on stderr.  File-level findings only — prettier doesn't report
        line numbers, and "the whole file's formatting is off" is
        accurately a file-level problem anyway.
        """
        result = self._run_command(
            ["npx", "prettier", "--check", "."],
            cwd=project_root,
            timeout=60,
        )

        if result.success:
            return []

        findings: List[Finding] = []
        for line in result.output.split("\n"):
            stripped = line.strip()
            # ``[warn] src/foo.js`` — the file path is everything after
            # the bracket tag.  Prettier also emits a summary line
            # (``[warn] Code style issues found in N files...``) which
            # doesn't look like a path; skip anything without a dot.
            if stripped.startswith("[warn] ") and "." in stripped:
                path = stripped[7:].strip()
                # Summary line guard — real paths don't contain spaces
                # in prettier's output (it quotes them if they do, but
                # the common case is space-free).  "Code style issues
                # found" has spaces and fails this.
                if " " not in path:
                    findings.append(Finding(message="needs prettier", file=path))

        if not findings:
            # Prettier failed but we couldn't parse file paths (exit 2,
            # config error, etc.).  Surface the raw output.
            findings.append(Finding(message=f"Prettier: {result.output.strip()[:200]}"))

        return findings
