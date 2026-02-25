"""Code duplication detection using jscpd.

Detects copy-paste code across multiple languages.
Reports specific file pairs and line ranges for deduplication.

Note: This is a cross-cutting quality check that works across
all languages supported by jscpd.
"""

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

from slopmop.checks.base import BaseCheck, ConfigField, Flaw, GateCategory
from slopmop.core.result import CheckResult, CheckStatus

DEFAULT_THRESHOLD = 5.0  # Percent duplication allowed
MIN_TOKENS = 50
MIN_LINES = 5


class SourceDuplicationCheck(BaseCheck):
    """Cross-language code duplication detection.

    Wraps jscpd to detect copy-paste code across Python, JavaScript,
    TypeScript, and other languages. Reports specific file pairs and
    line ranges so you know exactly what to deduplicate.

    Profiles: commit, pr

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

    Re-validate:
      ./sm validate quality:source-duplication --verbose
    """

    def __init__(self, config: Dict[str, Any], threshold: float = DEFAULT_THRESHOLD):
        super().__init__(config)
        self.threshold = config.get("threshold", threshold)

    @property
    def name(self) -> str:
        return "source-duplication"

    @property
    def display_name(self) -> str:
        return "📋 Source Duplication"

    @property
    def category(self) -> GateCategory:
        return GateCategory.MYOPIA

    @property
    def flaw(self) -> Flaw:
        return Flaw.MYOPIA

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
    ]

    def _check_jscpd_availability(self, project_root: str) -> Optional[str]:
        """Check if jscpd is available. Returns error message or None."""
        result = self._run_command(
            ["npx", "jscpd", "--version"], cwd=project_root, timeout=30
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

        return [
            "npx",
            "jscpd",
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
        duplicates = report.get("duplicates", [])
        stats = report.get("statistics", {})
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

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error="Excessive code duplication detected",
            fix_suggestion="Extract duplicated code into shared functions or modules.",
        )

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()

        # Check jscpd availability
        error = self._check_jscpd_availability(project_root)
        if error:
            return self._create_result(
                status=CheckStatus.WARNED,
                duration=time.time() - start_time,
                error=error,
                fix_suggestion="Install jscpd: npm install -g jscpd",
            )

        # Get config values
        min_tokens = self.config.get("min_tokens", MIN_TOKENS)
        min_lines = self.config.get("min_lines", MIN_LINES)
        include_dirs = self.config.get("include_dirs", ["."])
        if not include_dirs:
            include_dirs = ["."]

        with tempfile.TemporaryDirectory(prefix="jscpd-") as temp_dir:
            report_output = os.path.join(temp_dir, "jscpd-report")
            cmd = self._build_jscpd_command(
                report_output, include_dirs, min_tokens, min_lines
            )

            result = self._run_command(cmd, cwd=project_root, timeout=300)
            duration = time.time() - start_time

            report_path = os.path.join(report_output, "jscpd-report.json")
            if not os.path.exists(report_path):
                if result.returncode == 0:
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
