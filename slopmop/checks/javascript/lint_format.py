"""JavaScript lint and format check using ESLint and Prettier."""

import json
import logging
import os
import time
from typing import List, Optional, Tuple

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    RemediationChurn,
    ToolContext,
)
from slopmop.checks.mixins import JavaScriptCheckMixin
from slopmop.constants import ISSUES_FOUND_TEMPLATE, NPM_INSTALL_FAILED
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

logger = logging.getLogger(__name__)


class JavaScriptLintFormatCheck(BaseCheck, JavaScriptCheckMixin):
    """JavaScript/TypeScript lint and format enforcement.

    For Node projects: wraps ESLint and Prettier.
    For Deno projects: wraps ``deno lint`` and ``deno fmt``.

    Auto-fix runs the appropriate tool's fix mode before checking.
    Node projects get npm dependency installation automatically if
    node_modules/ is missing.

    Level: swab

    Configuration:
      Node: uses project's .eslintrc and .prettierrc.
      Deno: uses project's deno.json lint/fmt config.

    Common failures:
      ESLint errors: Run ``npx eslint . --fix`` to auto-fix.
      Prettier drift: Run ``npx prettier --write .`` to reformat.
      deno lint errors: Run ``deno lint --fix``.
      deno fmt drift: Run ``deno fmt``.

    Re-check:
      sm swab -g laziness:sloppy-formatting.js --verbose
    """

    # Dual-context gate: NODE for npm/npx projects, DENO for deno projects.
    # is_applicable() accepts both; run()/auto_fix() branch at runtime.
    # Declared as NODE since that's the original/majority case.
    tool_context = ToolContext.NODE
    role = CheckRole.FOUNDATION
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY

    @property
    def name(self) -> str:
        return "sloppy-formatting.js"

    @property
    def display_name(self) -> str:
        return "🎨 Lint & Format (JS/TS)"

    @property
    def gate_description(self) -> str:
        return "🎨 Lint + Format — ESLint/Prettier or deno lint/fmt (auto-fix 🔧)"

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
        return self.is_javascript_project(project_root) or self.is_deno_project(
            project_root
        )

    def skip_reason(self, project_root: str) -> str:
        return (
            "No package.json or deno.json found "
            "(not a JavaScript/TypeScript project)"
        )

    def can_auto_fix(self) -> bool:
        return True

    def auto_fix(self, project_root: str) -> bool:
        """Auto-fix formatting issues."""
        is_deno = self.is_deno_project(project_root)
        has_node = self.has_package_json(project_root)
        if is_deno:
            fixed = self._auto_fix_deno(project_root)
            if has_node:
                fixed = self._auto_fix_node(project_root) or fixed
            return fixed
        return self._auto_fix_node(project_root)

    # ------------------------------------------------------------------
    @staticmethod
    def _get_deno_target_dirs(project_root: str) -> List[str]:
        """Extract lint/fmt target directories from package.json scripts.

        Projects often scope ``deno lint`` / ``deno fmt`` to a subdirectory
        (e.g. ``"lint": "deno lint supabase/functions/"``).  When target
        dirs are found, we pass them explicitly so the gate doesn't lint
        files outside the project's intended scope.

        Returns an empty list when no scoped targets are detected (bare
        ``deno lint`` / ``deno fmt`` with no path argument).
        """
        pkg_path = os.path.join(project_root, "package.json")
        if not os.path.isfile(pkg_path):
            return []

        try:
            with open(pkg_path) as fh:
                pkg = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []

        scripts = pkg.get("scripts", {})
        targets: List[str] = []
        for _name, cmd in scripts.items():
            if not isinstance(cmd, str):
                continue
            # Match patterns like "deno lint supabase/functions/"
            for prefix in ("deno lint ", "deno fmt "):
                if prefix in cmd:
                    # Take the token immediately after the prefix
                    rest = cmd.split(prefix, 1)[1].strip()
                    path_arg = rest.split()[0] if rest else ""
                    # Only accept relative paths (not flags)
                    if path_arg and not path_arg.startswith("-"):
                        resolved = os.path.join(project_root, path_arg)
                        if os.path.isdir(resolved) and path_arg not in targets:
                            targets.append(path_arg)
        return targets

    def _auto_fix_deno(self, project_root: str) -> bool:
        fixed = False
        targets = self._get_deno_target_dirs(project_root)
        result = self._run_command(
            ["deno", "lint", "--fix"] + targets,
            cwd=project_root,
            timeout=60,
        )
        if result.success:
            fixed = True
        result = self._run_command(
            ["deno", "fmt"] + targets,
            cwd=project_root,
            timeout=60,
        )
        if result.success:
            fixed = True
        return fixed

    # ------------------------------------------------------------------
    # Node path
    # ------------------------------------------------------------------

    def _auto_fix_node(self, project_root: str) -> bool:
        fixed = False

        # Install deps if needed
        if not self.has_node_modules(project_root):
            npm_cmd = self._get_npm_install_command(project_root)
            self._run_command(npm_cmd, cwd=project_root, timeout=120)

        # Run ESLint fix
        result = self._run_command(
            ["npx", "--yes", "eslint", ".", "--fix"],
            cwd=project_root,
            timeout=60,
        )
        if result.success:
            fixed = True

        # Run Prettier
        result = self._run_command(
            ["npx", "--yes", "prettier", "--write", "."],
            cwd=project_root,
            timeout=60,
        )
        if result.success:
            fixed = True

        return fixed

    def run(self, project_root: str) -> CheckResult:
        """Run lint and format checks."""
        is_deno = self.is_deno_project(project_root)
        has_node = self.has_package_json(project_root)
        if is_deno and has_node:
            return self._run_hybrid(project_root)
        if is_deno:
            return self._run_deno(project_root)
        return self._run_node(project_root)

    # ------------------------------------------------------------------
    # Deno run
    # ------------------------------------------------------------------

    def _run_deno(self, project_root: str) -> CheckResult:
        start_time = time.time()
        issues: List[str] = []
        output_parts: List[str] = []

        # deno lint --json
        lint_result, lint_findings = self._check_deno_lint(project_root)
        if lint_result:
            issues.append(lint_result)
            output_parts.append(f"deno lint: {lint_result}")
        else:
            output_parts.append("deno lint: \u2705 No lint errors")

        # deno fmt --check
        fmt_result, fmt_findings = self._check_deno_fmt(project_root)
        if fmt_result:
            issues.append(fmt_result)
            output_parts.append(f"deno fmt: {fmt_result}")
        else:
            output_parts.append("deno fmt: \u2705 Formatting OK")

        duration = time.time() - start_time

        if issues:
            msg = ISSUES_FOUND_TEMPLATE.format(count=len(issues))
            all_findings = lint_findings + fmt_findings
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output="\n".join(output_parts),
                error=msg,
                fix_suggestion="Run: deno lint --fix && deno fmt",
                findings=all_findings
                or [Finding(message=msg, level=FindingLevel.ERROR)],
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output="\n".join(output_parts),
        )

    def _run_hybrid(self, project_root: str) -> CheckResult:
        """Run both Deno and Node checks for hybrid repos."""
        start_time = time.time()
        deno_result = self._run_deno(project_root)
        node_result = self._run_node(project_root)
        duration = time.time() - start_time

        deno_failed = deno_result.status in (CheckStatus.FAILED, CheckStatus.ERROR)
        node_failed = node_result.status in (CheckStatus.FAILED, CheckStatus.ERROR)

        if not deno_failed and not node_failed:
            output_parts: List[str] = []
            if deno_result.output:
                output_parts.append(f"[deno] {deno_result.output}")
            if node_result.output:
                output_parts.append(f"[node] {node_result.output}")
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output="\n".join(output_parts),
            )

        # Propagate ERROR status if either sub-result errored
        aggregate_status = CheckStatus.FAILED
        if (
            deno_result.status == CheckStatus.ERROR
            or node_result.status == CheckStatus.ERROR
        ):
            aggregate_status = CheckStatus.ERROR
        failed_count = int(deno_failed) + int(node_failed)
        msg = ISSUES_FOUND_TEMPLATE.format(count=failed_count)
        all_findings: List[Finding] = list(deno_result.findings) + list(
            node_result.findings
        )
        fail_parts: List[str] = []
        if deno_result.output:
            fail_parts.append(f"[deno]\n{deno_result.output}")
        if node_result.output:
            fail_parts.append(f"[node]\n{node_result.output}")
        return self._create_result(
            status=aggregate_status,
            duration=duration,
            output="\n".join(fail_parts),
            error=msg,
            fix_suggestion=(
                "Run: deno lint --fix && deno fmt "
                "&& npx eslint . --fix && npx prettier --write ."
            ),
            findings=all_findings or [Finding(message=msg, level=FindingLevel.ERROR)],
        )

    def _check_deno_lint(
        self, project_root: str
    ) -> Tuple[Optional[str], List[Finding]]:
        targets = self._get_deno_target_dirs(project_root)
        result = self._run_command(
            ["deno", "lint", "--json"] + targets,
            cwd=project_root,
            timeout=60,
        )
        if not result.success:
            findings: List[Finding] = []
            stdout = result.stdout.strip()
            if stdout:
                try:
                    data = json.loads(stdout)
                    for diag in data.get("diagnostics", []):
                        findings.append(
                            Finding(
                                message=diag.get("message", ""),
                                level=FindingLevel.ERROR,
                                file=diag.get("filename"),
                                line=diag.get("range", {}).get("start", {}).get("line"),
                                rule_id=diag.get("code"),
                            )
                        )
                    if not findings:
                        findings.append(
                            Finding(
                                message=(
                                    "deno lint exited with error"
                                    " but reported no diagnostics"
                                ),
                                level=FindingLevel.ERROR,
                            )
                        )
                except (json.JSONDecodeError, TypeError):
                    pass
                count = len(findings) if findings else len(stdout.split("\n"))
                return f"{count} lint issue(s)", findings
            message = (
                "deno lint failed with no output; check Deno "
                "installation and configuration."
            )
            findings.append(Finding(message=message, level=FindingLevel.ERROR))
            return message, findings
        return None, []

    def _check_deno_fmt(self, project_root: str) -> Tuple[Optional[str], List[Finding]]:
        targets = self._get_deno_target_dirs(project_root)
        result = self._run_command(
            ["deno", "fmt", "--check"] + targets,
            cwd=project_root,
            timeout=60,
        )
        if not result.success:
            msg = "Formatting issues found"
            # deno fmt --check lists misformatted files on stdout
            findings: List[Finding] = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if line:
                    findings.append(
                        Finding(
                            message=f"deno fmt: {line}",
                            level=FindingLevel.WARNING,
                        )
                    )
            if not findings:
                findings = [Finding(message=msg, level=FindingLevel.ERROR)]
            return msg, findings
        return None, []

    # ------------------------------------------------------------------
    # Node run
    # ------------------------------------------------------------------

    def _run_node(self, project_root: str) -> CheckResult:
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
            msg = ISSUES_FOUND_TEMPLATE.format(count=len(issues))
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
            ["npx", "--yes", "eslint", ".", "--format", "json"],
            cwd=project_root,
            timeout=60,
        )

        if not result.success and result.output.strip():
            # ESLint exits non-zero when no config is found — not a lint
            # failure, just an unconfigured project.  Don't count the
            # error message lines as lint issues.
            if "couldn't find a configuration file" in result.output.lower():
                logger.debug("ESLint: no configuration file found — skipping")
                return None, []

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
            ["npx", "--yes", "prettier", "--check", "."],
            cwd=project_root,
            timeout=60,
        )

        if not result.success:
            return "Formatting issues found"
        return None
