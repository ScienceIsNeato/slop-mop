"""JavaScript coverage threshold check.

Enforces minimum coverage thresholds for JS/TS projects.
Parses Jest coverage output to verify line coverage meets requirements.
"""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    RemediationChurn,
    ToolContext,
)
from slopmop.checks.constants import (
    JS_NO_TESTS_FOUND_EXPECTED,
    JS_NO_TESTS_FOUND_JEST,
    js_no_tests_fix_suggestion,
)
from slopmop.checks.mixins import JavaScriptCheckMixin
from slopmop.constants import (
    COVERAGE_BELOW_THRESHOLD,
    COVERAGE_GUIDANCE_FOOTER,
    COVERAGE_MEETS_THRESHOLD,
    COVERAGE_STANDARDS_PREFIX,
    NPM_INSTALL_FAILED,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

DEFAULT_THRESHOLD = 80
MAX_FILES_TO_SHOW = 5


class JavaScriptCoverageCheck(BaseCheck, JavaScriptCheckMixin):
    """Jest coverage threshold enforcement.

    Wraps Jest with --coverageReporters=json-summary to parse
    line coverage. Falls back to parsing console output if the
    JSON summary isn't available.

    Level: swab

    Configuration:
      threshold: 80 — minimum line coverage percentage. Start
          lower on legacy codebases and ramp up over time.

    Common failures:
      Below threshold: The output lists files with lowest
          coverage. Write tests for those files.
      Coverage data unavailable: Ensure Jest is configured to
          produce coverage reports.

    Re-check:
      sm swab -g overconfidence:coverage-gaps.js --verbose
    """

    tool_context = ToolContext.NODE
    role = CheckRole.FOUNDATION
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY

    def __init__(self, config: Dict[str, Any], threshold: int = DEFAULT_THRESHOLD):
        super().__init__(config)
        self.threshold = config.get("threshold", threshold)

    @property
    def name(self) -> str:
        return "coverage-gaps.js"

    @property
    def display_name(self) -> str:
        return "📊 Coverage (JavaScript, Jest)"

    @property
    def gate_description(self) -> str:
        return "📊 JavaScript coverage analysis"

    @property
    def category(self) -> GateCategory:
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

    @property
    def depends_on(self) -> List[str]:
        return ["overconfidence:untested-code.js"]

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="threshold",
                field_type="integer",
                default=80,
                description="Minimum coverage percentage required",
                min_value=0,
                max_value=100,
                permissiveness="higher_is_stricter",
            ),
        ]

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping — delegate to JavaScriptCheckMixin."""
        return JavaScriptCheckMixin.skip_reason(self, project_root)

    def is_applicable(self, project_root: str) -> bool:
        return self.is_javascript_project(project_root)

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()
        if not self.has_javascript_test_files(project_root):
            return self._no_tests_result(
                message=JS_NO_TESTS_FOUND_EXPECTED,
                duration=time.time() - start_time,
            )

        dep_result = self._ensure_dependencies(project_root, start_time)
        if dep_result is not None:
            return dep_result

        # Run Jest with coverage and JSON reporter
        result = self._run_command(
            [
                "npx",
                "--yes",
                "jest",
                "--ci",
                "--coverage",
                "--coverageReporters=json-summary",
            ],
            cwd=project_root,
            timeout=300,
        )
        duration = time.time() - start_time

        # Parse coverage from JSON summary
        coverage_data = self._parse_coverage_json(project_root)
        if coverage_data:
            return self._evaluate_coverage(coverage_data, result.output, duration)

        # Fallback: parse from console output
        coverage = self._parse_coverage_output(result.output)
        fallback_result = self._evaluate_console_coverage(coverage, duration)
        if fallback_result is not None:
            return fallback_result

        if "No tests found" in result.output:
            return self._no_tests_result(
                message=JS_NO_TESTS_FOUND_JEST,
                duration=duration,
                output=result.output,
            )

        # Can't determine coverage
        if result.success:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output="Tests passed (coverage data unavailable)",
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=result.output,
            error="Jest tests failed",
            findings=[Finding(message="Jest tests failed", level=FindingLevel.ERROR)],
        )

    def _no_tests_result(
        self, message: str, duration: float, output: Optional[str] = None
    ) -> CheckResult:
        out = output if output is not None else message
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            error=message,
            output=out,
            fix_suggestion=js_no_tests_fix_suggestion(self.verify_command),
            findings=[Finding(message=message, level=FindingLevel.ERROR)],
        )

    def _ensure_dependencies(
        self, project_root: str, start_time: float
    ) -> Optional[CheckResult]:
        if self.has_node_modules(project_root):
            return None
        npm_cmd = self._get_npm_install_command(project_root)
        npm_result = self._run_command(npm_cmd, cwd=project_root, timeout=120)
        if npm_result.success:
            return None
        return self._create_result(
            status=CheckStatus.ERROR,
            duration=time.time() - start_time,
            error=NPM_INSTALL_FAILED,
            output=npm_result.output,
        )

    def _evaluate_console_coverage(
        self, coverage: Optional[float], duration: float
    ) -> Optional[CheckResult]:
        if coverage is None:
            return None
        if coverage >= self.threshold:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=COVERAGE_MEETS_THRESHOLD,
            )
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=(
                COVERAGE_STANDARDS_PREFIX
                + "Add high-quality test coverage to the codebase.\n\n"
                + COVERAGE_GUIDANCE_FOOTER
            ),
            error=COVERAGE_BELOW_THRESHOLD,
            fix_suggestion="Add tests to increase coverage.",
            findings=[
                Finding(
                    message=f"Coverage {coverage:.1f}% below {self.threshold}%",
                    level=FindingLevel.ERROR,
                )
            ],
        )

    def _parse_coverage_json(self, project_root: str) -> Optional[Dict[str, Any]]:
        """Parse coverage-summary.json if available."""
        summary_path = os.path.join(project_root, "coverage", "coverage-summary.json")
        if not os.path.exists(summary_path):
            return None
        try:
            with open(summary_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    @staticmethod
    def _as_pct(v: Any) -> float:
        """Coerce Jest's ``pct`` field into a comparable float.

        Jest emits ``"pct": "Unknown"`` (a string) in
        ``coverage-summary.json`` when a file has zero executable
        statements — typically type-only modules or empty barrel
        files.  Comparing that against an int threshold raises
        ``TypeError: '>=' not supported between 'str' and 'int'``
        and the gate ERRORS instead of reporting.  Treat anything
        non-numeric as 0.0: it'll show up in the low-coverage list
        where a human can decide if the file needs tests or an
        exclusion.
        """
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def _evaluate_coverage(
        self, data: Dict[str, Any], output: str, duration: float
    ) -> CheckResult:
        """Evaluate coverage from parsed JSON data."""
        total = data.get("total", {})
        lines = total.get("lines", {})
        pct = self._as_pct(lines.get("pct", 0))

        if pct >= self.threshold:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=COVERAGE_MEETS_THRESHOLD,
            )

        # Find lowest coverage files
        low_files: List[tuple[str, float]] = []
        for path, stats in data.items():
            if path == "total":
                continue
            file_pct = self._as_pct(stats.get("lines", {}).get("pct", 100))
            if file_pct < self.threshold:
                low_files.append((path, file_pct))

        low_files.sort(key=lambda x: x[1])

        lines = [
            COVERAGE_STANDARDS_PREFIX
            + "Add high-quality test coverage to the following areas:",
            "",
        ]
        for path, file_pct in low_files[:MAX_FILES_TO_SHOW]:
            lines.append(f"  {path}")
        lines.append("")
        lines.append(COVERAGE_GUIDANCE_FOOTER)

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output="\n".join(lines),
            error=COVERAGE_BELOW_THRESHOLD,
            fix_suggestion="Add tests to increase coverage.",
            findings=[
                Finding(
                    message=f"Coverage {file_pct:.1f}% below {self.threshold}%",
                    file=path,
                    level=FindingLevel.ERROR,
                )
                for path, file_pct in low_files
            ],
        )

    def _parse_coverage_output(self, output: str) -> Optional[float]:
        """Extract line coverage percentage from Jest console output."""
        # Look for "All files" line with coverage percentages
        for line in output.splitlines():
            if "All files" in line:
                # Format: All files | 85.7 | 80 | 90 | 85.7 |
                parts = line.split("|")
                if len(parts) >= 5:
                    try:
                        return float(parts[4].strip())  # Lines column
                    except ValueError:
                        pass
        # Try regex fallback
        match = re.search(r"Lines\s*:\s*([\d.]+)%", output)
        if match:
            return float(match.group(1))
        return None
