"""Repeated code detection using jscpd.

Detects copy-paste code across multiple languages.
Reports specific file pairs and line ranges for deduplication.

Note: This is a cross-cutting quality check that works across
all languages supported by jscpd.

Ambiguity mine detection (duplicate function names across files)
has been extracted into its own check: ``myopia:ambiguity-mines.py``.
"""

import json
import os
import tempfile
import time
from pathlib import PurePath
from typing import Any, Dict, List, Optional

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    RemediationChurn,
    ScopeInfo,
    ToolContext,
    count_source_scope,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

DEFAULT_THRESHOLD = 5.0  # Percent duplication allowed
MIN_TOKENS = 50
MIN_LINES = 5


class RepeatedCodeCheck(BaseCheck):
    """Cross-language repeated code detection.

    Wraps jscpd to detect copy-paste code across Python, JavaScript,
    TypeScript, and other languages. Reports specific file pairs and
    line ranges so you know exactly what to deduplicate.

    Level: swab

    Configuration:
      threshold: 5 — maximum allowed duplication percentage. 5% is
          generous; tighten to 2-3% for mature codebases.
      include_dirs: ["."] — directories to scan.
      min_tokens: 50 — minimum token count to consider a block as
          duplicate. Filters trivial matches (imports, boilerplate).
      min_lines: 5 — minimum line count for a duplicate block.
      exclude_dirs: [] — extra dirs to skip (node_modules, venv,
          etc. are always excluded).

    Common failures:
      Duplication exceeds threshold: Extract the duplicated code
          into a shared function or module. The output shows the
          specific file pairs and line ranges.
      jscpd not available: npm install -g jscpd

    Re-check:
      sm swab -g laziness:repeated-code --verbose
    """

    tool_context = ToolContext.NODE
    role = CheckRole.FOUNDATION
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_VERY_LIKELY

    def __init__(self, config: Dict[str, Any], threshold: float = DEFAULT_THRESHOLD):
        super().__init__(config)
        self.threshold = config.get("threshold", threshold)

    @property
    def name(self) -> str:
        return "repeated-code"

    @property
    def display_name(self) -> str:
        return "📋 Repeated Code (jscpd clone detection)"

    @property
    def gate_description(self) -> str:
        return "📋 Code clone detection (jscpd)"

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
                name="threshold",
                field_type="integer",
                default=5,
                description="Maximum allowed duplication percentage",
                min_value=0,
                max_value=100,
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="include_dirs",
                field_type="string[]",
                default=["."],
                description="Directories to scan for duplication",
                permissiveness="more_is_stricter",
            ),
            ConfigField(
                name="min_tokens",
                field_type="integer",
                default=50,
                description="Minimum token count to consider as duplicate",
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="min_lines",
                field_type="integer",
                default=5,
                description="Minimum line count to consider as duplicate",
                permissiveness="lower_is_stricter",
            ),
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description="Additional directories to exclude from duplication scanning",
                permissiveness="fewer_is_stricter",
            ),
        ]

    def cache_inputs(self, project_root: str) -> Optional[str]:
        from slopmop.core.cache import hash_file_scope

        dirs = self.config.get("include_dirs", ["."])
        if not dirs:
            dirs = ["."]
        exclude = set(self.config.get("exclude_dirs", []))
        exts = {".py", ".js", ".ts", ".jsx", ".tsx"}
        return hash_file_scope(
            project_root,
            dirs,
            exts,
            self.config,
            exclude_dirs=exclude,
        )

    def is_applicable(self, project_root: str) -> bool:
        # Applicable to any project with code
        for ext in [".py", ".js", ".ts", ".jsx", ".tsx"]:
            for root, _, files in os.walk(project_root):
                if any(f.endswith(ext) for f in files):
                    return True
        return False

    def skip_reason(self, project_root: str) -> str:
        """Return skip reason when no source code is detected."""
        # Check for source files first
        has_code = False
        for ext in [".py", ".js", ".ts", ".jsx", ".tsx"]:
            for root, _, files in os.walk(project_root):
                if any(f.endswith(ext) for f in files):
                    has_code = True
                    break
            if has_code:
                break
        if not has_code:
            return "No Python or JavaScript/TypeScript source files found"
        return "Duplication check not applicable"

    # Default directories/files to ignore (build artifacts, caches, vendored)
    _DEFAULT_IGNORES = [
        "node_modules",
        "dist",
        "build",
        ".git",
        ".slopmop",
        "__pycache__",
        ".venv",
        "venv",
        "coverage",
        "coverage.xml",  # pytest-cov build artifact
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        "htmlcov",
        "*.egg-info",
        "tools",  # vendored third-party tools
        "migrations",  # DB migrations are intentionally repetitive
        "alembic",  # Alembic revisions are intentionally repetitive
        "**/migrations/**",
        "**/alembic/**",
    ]

    def _check_jscpd_availability(self, project_root: str) -> Optional[str]:
        """Check if jscpd is available. Returns error message or None."""
        result = self._run_command(
            ["npx", "--yes", "jscpd", "--version"], cwd=project_root, timeout=30
        )
        if result.returncode != 0:
            return "jscpd not available"
        return None

    def _build_jscpd_command(
        self,
        report_output: str,
        include_dirs: list[str],
        min_tokens: int,
        min_lines: int,
    ) -> list[str]:
        """Build the jscpd command with all arguments."""
        config_excludes = self.config.get("exclude_dirs", [])
        all_ignores = list(dict.fromkeys(self._DEFAULT_IGNORES + config_excludes))
        ignore_str = ",".join(all_ignores)

        # Restrict formats to match cache_inputs/is_applicable — otherwise
        # jscpd scans every file type it recognises (SVG, HTML, markdown, …)
        # and flags e.g. logo assets as "code duplication".
        return [
            "npx",
            "--yes",
            "jscpd",
            "--format",
            "python,javascript,typescript,jsx,tsx",
            "--min-tokens",
            str(min_tokens),
            "--min-lines",
            str(min_lines),
            "--threshold",
            str(self.threshold),
            "--reporters",
            "json",
            "--output",
            report_output,
            "--ignore",
            ignore_str + ",cursor-rules,**/__tests__/**,**/*.test.*,**/*.spec.*",
        ] + include_dirs

    def _parse_report(self, report_path: str) -> Optional[dict[str, Any]]:
        """Parse jscpd JSON report. Returns None on error."""
        try:
            with open(report_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def _format_result(self, report: dict[str, Any], duration: float) -> CheckResult:
        """Format the check result from parsed report."""
        raw_duplicates = report.get("duplicates", [])
        duplicates = self._filter_duplicates(raw_duplicates)
        stats = report.get("statistics", {})
        total_lines = stats.get("total", {}).get("lines", 0)
        if len(duplicates) < len(raw_duplicates) and total_lines > 0:
            # Recompute percentage from filtered set using original total lines
            dup_lines = sum(d.get("lines", 0) for d in duplicates)
            total_percentage = (dup_lines / total_lines) * 100
        else:
            total_percentage = stats.get("total", {}).get("percentage", 0)

        if total_percentage <= self.threshold:
            if len(duplicates) == 0:
                output_msg = "No duplication detected"
            else:
                output_msg = (
                    f"Duplication at {total_percentage:.1f}% "
                    f"(threshold: {self.threshold}%). "
                    f"{len(duplicates)} clone(s) found but within limits."
                )
            return self._create_result(
                status=CheckStatus.PASSED, duration=duration, output=output_msg
            )

        # Format violation details
        violations = self._format_duplicates(duplicates)
        detail = "Code duplication exceeds acceptable levels.\n\n"
        detail += "Duplicate blocks:\n" + "\n".join(violations[:10])
        if len(violations) > 10:
            detail += f"\n... and {len(violations) - 10} more"

        # Per-clone findings anchored at the first file's start line
        findings: List[Finding] = []
        for dup in duplicates:
            first = dup.get("firstFile", {})
            second = dup.get("secondFile", {})
            start = first.get("startLoc", {}).get("line")
            end = first.get("endLoc", {}).get("line")
            fname = first.get("name")
            sname = second.get("name", "?")
            sline = second.get("startLoc", {}).get("line", "?")
            if fname:
                findings.append(
                    Finding(
                        message=f"Duplicate of {sname}:{sline} ({dup.get('lines', 0)} lines)",
                        level=FindingLevel.ERROR,
                        file=fname,
                        line=start if isinstance(start, int) else None,
                        end_line=end if isinstance(end, int) else None,
                    )
                )
        if not findings:
            findings = [
                Finding(
                    message=f"Duplication {total_percentage:.1f}% exceeds {self.threshold}%",
                    level=FindingLevel.ERROR,
                )
            ]

        # Summarise which files dominate — if 140 of 162 findings are
        # in tests/, the fix is an exclusion, not a refactor.
        file_counts: dict[str, int] = {}
        for f in findings:
            if f.file:
                file_counts[f.file] = file_counts.get(f.file, 0) + 1
        top = sorted(file_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        top_str = ", ".join(f"{fn} ({n})" for fn, n in top) if top else "?"

        fix = (
            "Extract real clones into shared helpers. "
            f"Top offenders: {top_str}. "
            "If duplication is in tests, examples, or generated code, "
            "add those paths to checks.repeated-code.exclude_dirs "
            "in .sb_config.json — don't refactor test boilerplate."
        )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error="Excessive code duplication detected",
            fix_suggestion=fix,
            findings=findings,
        )

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()

        include_dirs = self.config.get("include_dirs", ["."])
        if not include_dirs:
            include_dirs = ["."]

        # Check jscpd availability
        jscpd_error = self._check_jscpd_availability(project_root)
        if jscpd_error:
            duration = time.time() - start_time
            return self._create_result(
                status=CheckStatus.WARNED,
                duration=duration,
                error=jscpd_error,
                fix_suggestion="Install jscpd: npm install -g jscpd",
                findings=[Finding(message=jscpd_error, level=FindingLevel.WARNING)],
            )

        # Get config values
        min_tokens = self.config.get("min_tokens", MIN_TOKENS)
        min_lines = self.config.get("min_lines", MIN_LINES)

        with tempfile.TemporaryDirectory(prefix="jscpd-") as temp_dir:
            report_output = os.path.join(temp_dir, "jscpd-report")
            cmd = self._build_jscpd_command(
                report_output, include_dirs, min_tokens, min_lines
            )

            result = self._run_command(cmd, cwd=project_root, timeout=300)
            duration = time.time() - start_time

            report_path = os.path.join(report_output, "jscpd-report.json")
            if not os.path.exists(report_path):
                # jscpd produces no report when it finds nothing to scan.
                # This happens when all files are excluded by --ignore patterns
                # (exit 2) or when the scan area is genuinely empty (exit 0).
                # Both cases mean 0% duplication — treat as PASSED.
                if result.returncode in {0, 2}:
                    return self._create_result(
                        status=CheckStatus.PASSED,
                        duration=duration,
                        output="No duplication detected",
                    )
                return self._create_result(
                    status=CheckStatus.ERROR,
                    duration=duration,
                    error=result.stderr or "jscpd failed to produce report",
                )

            report = self._parse_report(report_path)
            if report is None:
                return self._create_result(
                    status=CheckStatus.ERROR,
                    duration=duration,
                    error="Failed to parse jscpd report",
                )

            return self._format_result(report, duration)

    def measure_scope(self, project_root: str) -> Optional[ScopeInfo]:
        """Measure scope — counts files across all supported languages."""
        include_dirs = self.config.get("include_dirs") or ["."]
        return count_source_scope(
            project_root,
            include_dirs=list(include_dirs),
            extensions={".py", ".js", ".ts", ".jsx", ".tsx"},
        )

    @staticmethod
    def _path_excluded(file_path: str, patterns: List[str]) -> bool:
        """Return True if file_path matches any exclude pattern."""
        pure = PurePath(file_path)
        for pattern in patterns:
            if pure.match(pattern):
                return True
            # Plain names with no glob chars: match as a path component
            if not any(c in pattern for c in "*?[{"):
                if pattern in pure.parts:
                    return True
        return False

    def _filter_duplicates(
        self, duplicates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Remove pairs where either file matches an exclude_dirs pattern.

        This is a Python-level safety net that ensures exclude_dirs works
        even when jscpd's own --ignore flag behaves differently across
        versions or environments.
        """
        config_excludes = self.config.get("exclude_dirs", [])
        if not config_excludes:
            return duplicates
        return [
            dup
            for dup in duplicates
            if not (
                self._path_excluded(
                    dup.get("firstFile", {}).get("name", ""), config_excludes
                )
                or self._path_excluded(
                    dup.get("secondFile", {}).get("name", ""), config_excludes
                )
            )
        ]

    def _format_duplicates(self, duplicates: List[Dict[str, Any]]) -> List[str]:
        """Format duplicate entries for display."""
        violations: List[str] = []
        for dup in duplicates:
            first = dup.get("firstFile", {})
            second = dup.get("secondFile", {})
            lines = dup.get("lines", 0)
            violations.append(
                f"  {first.get('name', '?')}:{first.get('startLoc', {}).get('line', '?')}-"
                f"{first.get('endLoc', {}).get('line', '?')} ↔ "
                f"{second.get('name', '?')}:{second.get('startLoc', {}).get('line', '?')}-"
                f"{second.get('endLoc', {}).get('line', '?')} ({lines} lines)"
            )
        return violations
