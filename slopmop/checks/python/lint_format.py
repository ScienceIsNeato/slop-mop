"""Python lint and format check using black, isort, autoflake, and flake8.

This check:
1. Auto-removes unused imports with autoflake (or ruff when configured)
2. Auto-fixes formatting with black (or ruff when configured)
3. Auto-fixes import order with isort (or ruff when configured)
4. Checks for critical lint errors with flake8

When the project already pins ruff (detected via pyproject.toml, ruff.toml,
or .pre-commit-config.yaml), the gate defers to ruff format + ruff check
instead of running black/isort/autoflake.  This prevents formatting churn
when the host's CI would immediately reformat slop-mop's output.
"""

import os
import re
import time
from typing import List, Optional

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    RemediationChurn,
    Requirements,
    ToolContext,
    pip_cli_requirement,
    resolve_tool_paths,
)
from slopmop.checks.constants import COMMAND_NOT_FOUND
from slopmop.checks.mixins import PythonCheckMixin
from slopmop.checks.python._host_formatter import detect_host_python_formatter
from slopmop.checks.timeouts import DEFAULT_TOOL_TIMEOUT
from slopmop.constants import ISSUES_FOUND_TEMPLATE
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

# flake8 default format: path:line:col: CODE message
_FLAKE8_RE = re.compile(r"^(.+?):(\d+):(\d+): (\w+) (.+)$")

# Sentinel returned by _check_black when the tool itself is broken
# (e.g. missing dependency).  Distinguished from None (pass) and
# a string (real formatting failure) so that run() can report the
# skip without treating it as a pass.
_BLACK_SKIPPED = "__BLACK_SKIPPED_BROKEN_INSTALL__"
_RUFF_SKIPPED = "__RUFF_SKIPPED_NOT_INSTALLED__"

# Prefix carried by every "this tool ran out of time" message, so run() can
# tell a killed subprocess apart from a real finding. Without it, honest
# timeout TEXT still arrived as a FAILED result with an invented finding —
# the phantom this gate exists to prevent.
_TIMED_OUT_MARKER = "[timed-out]"

_DEFAULT_EXCLUDE_DIRS = [
    "venv",
    ".venv",
    "build",
    "dist",
    "node_modules",
    ".git",
    "cursor-rules",
    "tools",
    "__pycache__",
    # Framework-generated history or transient helpers: format/lint noise,
    # low signal for repository quality.
    "migrations",
    "alembic",
    "ephemeral",
]

# Black --extend-exclude regex built from _DEFAULT_EXCLUDE_DIRS so that
# recursive runs on a top-level package (e.g. "enterprise") don't descend
# into nested migration dirs like enterprise/migrations/versions/. (#263)
_BLACK_EXTEND_EXCLUDE = (
    r"/(" + "|".join(re.escape(d) for d in _DEFAULT_EXCLUDE_DIRS) + r")/"
)


def _is_import_error(output: str) -> bool:
    """True when output looks like a Python import/module-not-found error.

    Checks for error names at the *start* of a line (how Python
    tracebacks format them) to avoid false positives on filenames
    that happen to contain 'ImportError' or 'ModuleNotFoundError'.
    """
    for line in output.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("ModuleNotFoundError:", "ImportError:")):
            return True
    return False


class PythonLintFormatCheck(BaseCheck, PythonCheckMixin):
    """Python code formatting and lint enforcement.

    Wraps autoflake, black, isort, and flake8 to enforce consistent
    style and catch critical errors. Auto-fix runs autoflake (remove
    unused imports), black (formatting), and isort (import order)
    before checking with flake8.

    Level: swab

    Configuration:
      line_length: 88 — black's default; wide enough for modern
          screens, narrow enough to diff side-by-side.

    Common failures:
      Formatting drift: Run `sm swab -g laziness:sloppy-formatting.py` with
          auto-fix enabled. Black and isort will fix in place.
      Unused imports: autoflake removes them automatically during
          auto-fix. If you need to keep one, re-export it explicitly.
      Flake8 E9/F63/F7/F82: These are critical errors (syntax,
          assertion on tuples, undefined names). Fix the code.

    Re-check:
      sm swab -g laziness:sloppy-formatting.py --verbose
    """

    tool_context = ToolContext.SM_TOOL
    role = CheckRole.FOUNDATION

    def requirements(self) -> Requirements:
        # All optional: a missing formatter/linter is skipped with a note, not a
        # failure. _run_command resolves each (venv-aware) at invocation time.
        return Requirements(
            items=(
                pip_cli_requirement(
                    "black", "26.5.1", "code formatting", optional=True, extra="lint"
                ),
                pip_cli_requirement(
                    "isort", "8.0.1", "import sorting", optional=True, extra="lint"
                ),
                pip_cli_requirement(
                    "autoflake",
                    "2.3.3",
                    "removes unused imports/variables",
                    optional=True,
                    extra="lint",
                ),
                pip_cli_requirement(
                    "flake8", "7.3.0", "style linting", optional=True, extra="lint"
                ),
                pip_cli_requirement(
                    "ruff",
                    "0.16.3",
                    "fast linting + formatting",
                    optional=True,
                    extra="lint",
                ),
            )
        )

    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY
    is_formatting_gate = True

    @property
    def name(self) -> str:
        return "sloppy-formatting.py"

    @property
    def display_name(self) -> str:
        return "🎨 Lint & Format (autoflake, black, isort, flake8)"

    @property
    def gate_description(self) -> str:
        return "🎨 autoflake, black, isort, flake8 (supports auto-fix 🔧)"

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
                name="line_length",
                field_type="integer",
                default=88,
                description="Maximum line length for black",
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="tool_timeout",
                field_type="integer",
                default=DEFAULT_TOOL_TIMEOUT,
                description=(
                    "Seconds each formatter/linter subprocess may run. The "
                    "default suits most repos, but a large tree can format in "
                    "40-55s standalone and tip past it once scour runs gates "
                    "in parallel — which surfaced as a phantom formatting "
                    "finding. Raise this rather than narrowing what gets "
                    "formatted."
                ),
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="formatter",
                field_type="string",
                default="auto",
                choices=["auto", "ruff", "black", "none"],
                description=(
                    "Python formatter to use. Options: 'auto' (detect from project "
                    "config — default), 'ruff' (always use ruff format + ruff check), "
                    "'black' (always use autoflake + black + isort), 'none' (skip "
                    "formatting entirely — flake8 syntax checks still run). "
                    "Auto-detection checks pyproject.toml, .ruff.toml, and "
                    ".pre-commit-config.yaml."
                ),
            ),
        ]

    def _tool_timeout(self) -> int:
        """Per-subprocess ceiling, overridable via the ``tool_timeout`` config."""
        try:
            configured = int(self.config.get("tool_timeout", DEFAULT_TOOL_TIMEOUT))
        except (TypeError, ValueError):
            return DEFAULT_TOOL_TIMEOUT
        return configured if configured > 0 else DEFAULT_TOOL_TIMEOUT

    def _is_all_timeouts(self, issues: List[str]) -> bool:
        """True when every issue is a killed tool rather than a real finding."""
        return bool(issues) and all(_TIMED_OUT_MARKER in i for i in issues)

    def _timeout_warning(
        self, issues: List[str], output_parts: List[str], duration: float
    ) -> CheckResult:
        """WARNED, with no fabricated finding, for a run that only timed out.

        A killed tool reached no verdict, so FAILED plus an invented Finding
        would be exactly the phantom this gate exists to prevent.
        """
        return self._create_result(
            status=CheckStatus.WARNED,
            duration=duration,
            output="\n".join(output_parts),
            error="; ".join(issues),
            fix_suggestion=(
                "Raise this gate's tool_timeout, or narrow the scan with "
                "exclude_dirs."
            ),
        )

    def _timed_out_message(self, tool: str, result: object) -> Optional[str]:
        """Honest text for a killed subprocess, or None if it wasn't killed.

        A tool that ran out of time reached no verdict, so it says nothing
        about the code. Reporting it as "issues found" — with no file to look
        at — sends people hunting for formatting drift that was never
        detected. Name what happened and the knob that fixes it.
        """
        if not getattr(result, "timed_out", False):
            return None
        return (
            f"{_TIMED_OUT_MARKER} {tool} did not finish within "
            f"{self._tool_timeout()}s, so it reached no verdict — this is NOT "
            "a formatting finding. Large trees can tip past the limit when "
            "gates run in parallel; raise this gate's tool_timeout."
        )

    def _effective_formatter(self, project_root: str) -> Optional[str]:
        """Return 'ruff', 'black', or None (use black defaults).

        Respects an explicit 'formatter' config override; falls back to
        auto-detection via the project's own config files.
        """
        override = self.config.get("formatter")
        if override == "none":
            return "none"
        if override in ("ruff", "black"):
            return override
        # 'auto' or unset: detect from project
        return detect_host_python_formatter(project_root)

    def is_applicable(self, project_root: str) -> bool:
        return self.is_python_project(project_root)

    def can_auto_fix(self) -> bool:
        return True

    def auto_fix(self, project_root: str) -> bool:
        """Auto-fix formatting issues.

        Defers to the project's own formatter when one is configured
        (ruff), falling back to autoflake + black + isort otherwise.
        """
        formatter = self._effective_formatter(project_root)
        if formatter == "none":
            return False
        if formatter == "ruff":
            return self._auto_fix_ruff(project_root)
        return self._auto_fix_black(project_root)

    def _auto_fix_ruff(self, project_root: str) -> bool:
        """Format with ruff — defers to the project's own ruff config."""
        fixed = False

        # ruff format replaces black
        result = self._run_command(
            ["ruff", "format", "."],
            cwd=project_root,
            timeout=self._tool_timeout(),
        )
        if result.success:
            fixed = True

        # ruff check --fix --select I replaces isort; F401 replaces autoflake.
        # --select overrides pyproject config for this invocation so we touch
        # only style (not logic-altering rules).
        result = self._run_command(
            ["ruff", "check", "--fix", "--select", "I,F401", "."],
            cwd=project_root,
            timeout=self._tool_timeout(),
        )
        if result.success:
            fixed = True

        return fixed

    def _auto_fix_black(self, project_root: str) -> bool:
        """Format with autoflake + black + isort (slop-mop defaults)."""
        fixed = False

        # Find Python source directories to format
        targets = self._get_python_targets(project_root)
        if not targets:
            # Nothing the tools care about. Falling back to "." here would
            # format the entire tree, including everything git told us to skip.
            return False

        # Run autoflake first to remove unused imports
        result = self._run_command(
            [
                "autoflake",
                "--in-place",
                "--remove-all-unused-imports",
                "--recursive",
                f"--exclude={','.join(_DEFAULT_EXCLUDE_DIRS)}",
            ]
            + targets,
            cwd=project_root,
            timeout=self._tool_timeout(),
        )
        if result.success:
            fixed = True

        # Run black on each target.  --extend-exclude prevents recursive
        # descent into nested migration/alembic dirs (#263).
        for target in targets:
            result = self._run_command(
                [
                    "black",
                    "--line-length",
                    "88",
                    "--extend-exclude",
                    _BLACK_EXTEND_EXCLUDE,
                    target,
                ],
                cwd=project_root,
                timeout=self._tool_timeout(),
            )
            if result.success:
                fixed = True

        # Run isort — skip hidden directories to match _check_isort behaviour
        isort_cmd = ["isort", "--profile", "black"]
        isort_cmd.extend(f"--skip={name}" for name in _DEFAULT_EXCLUDE_DIRS)
        targets = self._get_python_targets(project_root)
        if not targets:
            # Nothing to sort. Report what earlier steps fixed rather
            # than None — this path returns a bool.
            return fixed
        isort_cmd.append("--skip-glob=.*")
        # Explicit targets, never ".": isort's --skip is a post-filter, so a
        # bare "." still walks (and opens) every file in a nested .venv.
        isort_cmd.extend(targets)
        result = self._run_command(
            isort_cmd, cwd=project_root, timeout=self._tool_timeout()
        )
        if result.success:
            fixed = True

        return fixed

    def _get_python_targets(self, project_root: str) -> List[str]:
        """Paths to hand the formatters and linters.

        This used to inspect only TOP-LEVEL entries, adding a directory just
        for holding ``__init__.py`` or being named src/tests/test/lib. A repo
        that keeps its code one level down — ``server/app`` next to
        ``client/`` — matched none of those, so the list came back EMPTY and
        flake8 silently checked nothing while reporting "no critical errors".
        A gate that passes without looking is worse than one that fails.

        The shared resolver walks the tree instead, pruning vendored and
        excluded directories at any depth, so nested layouts are found and a
        nested virtualenv still isn't scanned.
        """
        return resolve_tool_paths(
            project_root,
            exclude_dirs=self._configured_excludes(),
            extensions={".py", ".pyi"},
        )

    def _configured_excludes(self) -> List[str]:
        """This gate's default excludes plus anything the project configured."""
        configured = self.config.get("exclude_dirs", [])
        if isinstance(configured, str):
            configured = [configured]
        return list(_DEFAULT_EXCLUDE_DIRS) + list(configured)

    def _run_formatter_sections(
        self,
        formatter: Optional[str],
        project_root: str,
        issues: List[str],
        labeled_issues: List[tuple[str, str, bool]],
        section_findings: List[Finding],
        output_parts: List[str],
    ) -> str:
        """Run the formatter-mode sections, appending into the accumulators.

        Returns the fix hint for whichever mode ran. Split from run() so the
        orchestration stays under the sprawl limit this gate itself enforces.
        """
        if formatter == "none":
            output_parts.append("Formatting skipped (formatter: none)")
            fix_hint = "Run: flake8 --select=E9,F63,F7,F82,F401 . to check syntax"
        elif formatter == "ruff":
            # Check 1: ruff format
            fmt_result, fmt_findings = self._check_ruff_format(project_root)
            if fmt_result == _RUFF_SKIPPED:
                output_parts.append("Ruff format: ⚠️ Skipped (ruff not installed)")
            elif fmt_result:
                issues.append(fmt_result)
                labeled_issues.append(("Ruff format", fmt_result, bool(fmt_findings)))
                section_findings.extend(fmt_findings)
                output_parts.append(f"Ruff format: {fmt_result}")
            else:
                output_parts.append("Ruff format: ✅ Formatting OK")

            # Check 2: ruff import order
            import_result, import_findings = self._check_ruff_imports(project_root)
            if import_result == _RUFF_SKIPPED:
                output_parts.append("Ruff imports: ⚠️ Skipped (ruff not installed)")
            elif import_result:
                issues.append(import_result)
                labeled_issues.append(
                    ("Ruff imports", import_result, bool(import_findings))
                )
                section_findings.extend(import_findings)
                output_parts.append(f"Ruff imports: {import_result}")
            else:
                output_parts.append("Ruff imports: ✅ Import order OK")

            fix_hint = "Run: ruff format . && ruff check --fix --select I,F401 ."
        else:
            # Check 1: Black formatting
            black_result, black_findings = self._check_black(project_root)
            if black_result == _BLACK_SKIPPED:
                output_parts.append("Black: ⚠️ Skipped (broken installation)")
            elif black_result:
                issues.append(black_result)
                labeled_issues.append(("Black", black_result, bool(black_findings)))
                section_findings.extend(black_findings)
                output_parts.append(f"Black: {black_result}")
            else:
                output_parts.append("Black: ✅ Formatting OK")

            # Check 2: Isort imports
            isort_result, isort_findings = self._check_isort(project_root)
            if isort_result:
                issues.append(isort_result)
                labeled_issues.append(("Isort", isort_result, bool(isort_findings)))
                section_findings.extend(isort_findings)
                output_parts.append(f"Isort: {isort_result}")
            else:
                output_parts.append("Isort: ✅ Import order OK")

            fix_hint = "Run: black . && isort . to auto-fix formatting"

        return fix_hint

    def run(self, project_root: str) -> CheckResult:
        """Run lint and format checks.

        Uses ruff when the project has it configured; black/isort otherwise.
        Flake8 runs in both cases for critical syntax/undefined-name errors.
        """
        start_time = time.time()
        formatter = self._effective_formatter(project_root)
        issues: List[str] = []
        output_parts: List[str] = []
        # (label, section text) for every failed section, plus any per-file
        # findings the section could parse. The labels exist because a bare
        # count is what CI renders when findings carry nothing — a release
        # once stalled two gate cycles on "(location unknown) — 1 issue(s)
        # found" whose culprit was a single file the log named all along.
        labeled_issues: List[tuple[str, str, bool]] = []
        section_findings: List[Finding] = []

        fix_hint = self._run_formatter_sections(
            formatter,
            project_root,
            issues,
            labeled_issues,
            section_findings,
            output_parts,
        )

        # Check 3: Flake8 critical errors (always)
        flake8_result, flake8_findings = self._check_flake8(project_root)
        if flake8_result:
            issues.append(flake8_result)
            labeled_issues.append(("Flake8", flake8_result, bool(flake8_findings)))
            section_findings.extend(flake8_findings)
            output_parts.append(f"Flake8: {flake8_result}")
        else:
            output_parts.append("Flake8: ✅ No critical errors")

        duration = time.time() - start_time

        if issues:
            if self._is_all_timeouts(issues):
                return self._timeout_warning(issues, output_parts, duration)
            msg = ISSUES_FOUND_TEMPLATE.format(count=len(issues))
            # Every failed section must be visible in the findings — a bare
            # "N issue(s) found" with no file and no tool name renders as
            # "(location unknown)" in CI and tells the reader nothing; a
            # release once stalled two gate cycles tracing exactly that.
            # Sections that parsed file paths are already per-file findings;
            # a section that could not contributes its labeled text instead,
            # so the tool name and its output always reach the report.
            final_findings = list(section_findings)
            for label, text, had_findings in labeled_issues:
                if had_findings:
                    continue
                summary = text if len(text) <= 400 else text[:400] + " …"
                final_findings.append(
                    Finding(message=f"{label}: {summary}", level=FindingLevel.ERROR)
                )
            if not final_findings:
                final_findings = [Finding(message=msg, level=FindingLevel.ERROR)]
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output="\n".join(output_parts),
                error=msg,
                fix_suggestion=fix_hint,
                findings=final_findings,
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output="\n".join(output_parts),
        )

    @staticmethod
    def _files_to_findings(
        paths: List[str], message: str, project_root: str
    ) -> List[Finding]:
        """Per-file Findings with paths made project-relative.

        Tools print absolute paths when handed absolute targets; Finding.file
        is documented as relative-to-project-root, and SARIF/report rendering
        depends on it.
        """
        findings: List[Finding] = []
        for path in paths:
            rel = path
            try:
                if os.path.isabs(path):
                    candidate = os.path.relpath(path, project_root)
                    if not candidate.startswith(".."):
                        rel = candidate
            except ValueError:
                pass  # different drive on Windows — keep the absolute path
            findings.append(
                Finding(message=message, level=FindingLevel.ERROR, file=rel)
            )
        return findings

    def _check_ruff_format(
        self, project_root: str
    ) -> tuple[Optional[str], List[Finding]]:
        """Check ruff formatting (equivalent of black --check)."""
        result = self._run_command(
            ["ruff", "format", "--check", "."],
            cwd=project_root,
            timeout=self._tool_timeout(),
        )
        if not result.success:
            timed_out = self._timed_out_message("ruff format", result)
            if timed_out:
                return timed_out, []
            output = (result.output or "").strip()
            if COMMAND_NOT_FOUND in output:
                return _RUFF_SKIPPED, []
            # Two output shapes across ruff versions: older ruffs print
            # "Would reformat: path"; 0.16.x prints diagnostic blocks with
            # " --> path:line" markers (verified against the pinned 0.16.3).
            # Parsing only the old shape left Finding.file empty on exactly
            # the version we ship — location-less findings again.
            files = sorted(
                set(re.findall(r"^Would reformat: (.+)$", output, re.M))
                | set(re.findall(r"^\s*--> ([^:\n]+):\d+", output, re.M))
            )
            return output or "Ruff format check failed", self._files_to_findings(
                files, "ruff format would reformat this file", project_root
            )
        return None, []

    def _check_ruff_imports(
        self, project_root: str
    ) -> tuple[Optional[str], List[Finding]]:
        """Check import order with ruff (equivalent of isort --check-only)."""
        result = self._run_command(
            ["ruff", "check", "--select", "I", "."],
            cwd=project_root,
            timeout=self._tool_timeout(),
        )
        if not result.success:
            timed_out = self._timed_out_message("ruff check --select I", result)
            if timed_out:
                return timed_out, []
            output = (result.output or "").strip()
            if COMMAND_NOT_FOUND in output:
                return _RUFF_SKIPPED, []
            files = sorted(set(re.findall(r"^\s*--> ([^:\n]+):\d+", output, re.M)))
            findings = self._files_to_findings(
                files, "Import block is un-sorted (ruff --select I)", project_root
            )
            if output:
                lines = [line for line in output.splitlines() if line.strip()]
                if len(lines) <= 5:
                    return "Import order issues:\n  " + "\n  ".join(lines), findings
                shown = "\n  ".join(lines[:5])
                return (
                    f"Import order issues:\n  {shown}\n  ... and {len(lines)-5} more",
                    findings,
                )
            return "Import order issues found", findings
        return None, []

    def _check_black(self, project_root: str) -> tuple[Optional[str], List[Finding]]:
        """Check black formatting.

        In normal operation, auto_fix() runs first, so failures here are typically:
        - Syntax errors that black can't parse
        - Files black refuses to format
        If --no-auto-fix was used, may also see "would reformat" messages.
        """
        targets = self._get_python_targets(project_root)
        if not targets:
            return None, []  # No Python targets found

        # Run black --check on all targets, collect any failures
        all_output: List[str] = []
        any_failed = False

        for target in targets:
            result = self._run_command(
                [
                    "black",
                    "--check",
                    "--line-length",
                    "88",
                    "--extend-exclude",
                    _BLACK_EXTEND_EXCLUDE,
                    target,
                ],
                cwd=project_root,
                timeout=self._tool_timeout(),
            )
            if not result.success:
                timed_out = self._timed_out_message("black", result)
                if timed_out:
                    return timed_out, []
                output = (result.output or "").strip()
                # Distinguish tool-installation failures from real formatting
                # issues.  A broken black (missing dependency, bad interpreter,
                # import error) is not a code-quality finding — skip it.
                # Check line-starts to avoid false positives on filenames
                # that happen to contain "ImportError" or "ModuleNotFoundError".
                if _is_import_error(output):
                    return _BLACK_SKIPPED, []  # tool broken, not a code issue
                any_failed = True
                if output:
                    # Black outputs useful info like:
                    # "error: cannot format file.py: Cannot parse: 1:11: message"
                    # "would reformat file.py"
                    all_output.append(output)

        if not any_failed:
            return None, []

        # Combine and return black's actual output (it includes file:line info)
        combined = "\n".join(all_output)
        # The two failure shapes deserve different words: "would reformat" on
        # a file black REFUSED to parse would send the reader chasing style
        # drift when the file has a syntax error.
        drift = re.findall(r"^would reformat (.+)$", combined, re.M)
        broken = re.findall(r"^error: cannot format ([^:]+):.*$", combined, re.M)
        findings = self._files_to_findings(
            sorted(set(drift)), "black would reformat this file", project_root
        ) + self._files_to_findings(
            sorted(set(broken)),
            "black cannot format this file (parse error)",
            project_root,
        )
        if combined:
            return combined, findings
        return "Formatting check failed", findings

    def _check_isort(self, project_root: str) -> tuple[Optional[str], List[Finding]]:
        """Check isort import order."""
        isort_cmd = ["isort", "--check-only", "--profile", "black"]
        isort_cmd.extend(f"--skip={name}" for name in _DEFAULT_EXCLUDE_DIRS)
        # Skip hidden directories (e.g. .claude/, .git/) that contain
        # tool infrastructure rather than project source code.
        targets = self._get_python_targets(project_root)
        if not targets:
            return None, []  # nothing to sort
        isort_cmd.append("--skip-glob=.*")
        # Explicit targets, never ".": isort's --skip is a post-filter, so a
        # bare "." still walks (and opens) every file in a nested .venv.
        isort_cmd.extend(targets)
        result = self._run_command(
            isort_cmd, cwd=project_root, timeout=self._tool_timeout()
        )

        if not result.success:
            timed_out = self._timed_out_message("isort", result)
            if timed_out:
                return timed_out, []
            # isort outputs "ERROR: file.py ..." or "Skipped X files"
            # Extract file paths from output for actionable feedback
            output = result.output if result.output else ""
            error_lines = [
                line for line in output.split("\n") if line.startswith("ERROR:")
            ]
            if error_lines:
                # Extract file paths from "ERROR: path/to/file.py ..." lines
                file_names: List[str] = []
                for line in error_lines:
                    parts = line.split(" ")
                    if len(parts) >= 2:
                        file_names.append(str(parts[1]))
                if not file_names:
                    # ERROR lines whose shape we failed to parse: fall back to
                    # the generic message rather than a blank file list — the
                    # labeled-text fallback in run() then carries isort's
                    # actual output into the findings.
                    return "Import order issues found", []
                findings = self._files_to_findings(
                    file_names,
                    "Imports are incorrectly sorted (isort)",
                    project_root,
                )
                if len(file_names) <= 5:
                    files_str = "\n  ".join(file_names)
                    return f"Import order issues:\n  {files_str}", findings
                else:
                    shown = "\n  ".join(file_names[:5])
                    remaining = len(file_names) - 5
                    return (
                        f"Import order issues:\n  {shown}\n  ... and {remaining} more",
                        findings,
                    )
            return "Import order issues found", []
        return None, []

    def _check_flake8(self, project_root: str) -> tuple[Optional[str], List[Finding]]:
        """Check for critical flake8 errors.

        Scans only the configured include_dirs or auto-detected Python source
        directories.  Hidden directories (e.g. .claude/, .git/) are excluded
        via --extend-exclude since they contain tool infrastructure, not
        project source code.  If include_dirs explicitly includes hidden
        directories, they will still be scanned.
        """
        # Determine targets: configured include_dirs > auto-detected Python dirs
        include_dirs = self.config.get("include_dirs")
        if include_dirs:
            targets: List[str] = (
                [include_dirs] if isinstance(include_dirs, str) else list(include_dirs)
            )
        else:
            targets = self._get_python_targets(project_root)

        if not targets:
            return None, []  # No Python source directories to check

        # Build exclude list: base defaults + any configured exclude_dirs
        # Use --extend-exclude to preserve flake8's built-in defaults
        # (__pycache__, .tox, .nox, etc.) while adding our custom excludes.
        base_excludes = _DEFAULT_EXCLUDE_DIRS + [".*"]  # Hidden directories
        config_excludes = self.config.get("exclude_dirs", [])
        if isinstance(config_excludes, str):
            config_excludes = [config_excludes]
        all_excludes = base_excludes + list(config_excludes)

        result = self._run_command(
            [
                "flake8",
                "--select=E9,F63,F7,F82,F401",
                "--max-line-length=88",
                f"--extend-exclude={','.join(all_excludes)}",
            ]
            + targets,
            cwd=project_root,
            timeout=self._tool_timeout(),
        )

        timed_out = self._timed_out_message("flake8", result)
        if timed_out:
            return timed_out, []
        if not result.success and result.output.strip():
            lines = result.output.strip().split("\n")
            findings: List[Finding] = []
            for line in lines:
                m = _FLAKE8_RE.match(line)
                if m:
                    code = m.group(4)
                    findings.append(
                        Finding(
                            message=m.group(5),
                            level=(
                                FindingLevel.WARNING
                                if code.startswith("W")
                                else FindingLevel.ERROR
                            ),
                            file=m.group(1),
                            line=int(m.group(2)),
                            column=int(m.group(3)),
                            rule_id=code,
                        )
                    )

            # If no findings were created (output format unexpected), include raw output
            if not findings:
                findings.append(
                    Finding(
                        message=(
                            "Flake8 output could not be parsed with expected format. "
                            "Raw output:\n" + result.output[:500]
                        ),
                        level=FindingLevel.ERROR,
                    )
                )

            return (
                f"{len(lines)} critical error(s):\n" + "\n".join(lines[:5]),
                findings,
            )
        return None, []
