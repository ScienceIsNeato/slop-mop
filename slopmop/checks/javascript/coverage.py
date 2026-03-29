"""JavaScript coverage threshold check.

Enforces minimum coverage thresholds for JS/TS projects.
Parses either Jest coverage artifacts or Deno-produced coverage data
for hybrid repos that still want one coherent "is the changed JS/TS
code meaningfully covered?" gate.
"""

import json
import re
import shlex
import time
from pathlib import Path
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
DEFAULT_COVERAGE_COMMAND = (
    "npx --yes jest --ci --coverage --coverageReporters=json-summary"
)
DEFAULT_COVERAGE_REPORT_PATH = "coverage/coverage-summary.json"
DEFAULT_COVERAGE_FORMAT = "json-summary"


class JavaScriptCoverageCheck(BaseCheck, JavaScriptCheckMixin):
    """JavaScript/TypeScript coverage threshold enforcement.

    Runs a configurable coverage command, then parses either a
    Jest-style JSON summary, an lcov report, or a Deno raw coverage
    directory to evaluate line coverage. Defaults to Jest with
    ``coverage-summary.json`` for backwards compatibility.

    Why one gate instead of separate Jest/Deno variants?  The policy
    question is the same in both cases: did the project produce enough
    line coverage for the changed JavaScript/TypeScript code?  The
    runtime/tooling differs, but the remediation signal is shared, so
    the gate stays singular and only the artifact adapter changes.

    Level: swab

    Configuration:
      threshold: 80 — minimum line coverage percentage. Start
          lower on legacy codebases and ramp up over time.
      coverage_command: Command string parsed with ``shlex.split``
          into argv and executed without a shell. Defaults to Jest.
      coverage_report_path: Path to the generated coverage report,
          relative to project root. Defaults to
          ``coverage/coverage-summary.json``.
      coverage_format: ``json-summary``, ``lcov``, or ``deno``.

    Common failures:
      Below threshold: The output lists files with lowest
          coverage. Write tests for those files.
      Coverage data unavailable: Ensure the configured coverage
          command writes the configured report format/path.

    Re-check:
      sm swab -g overconfidence:coverage-gaps.js --verbose
    """

    # Dual-context gate: NODE for npm/jest projects, DENO for deno projects.
    # is_applicable() accepts both; run() branches at runtime based on
    # coverage_format config.  Declared as NODE since that is the
    # original/majority case.
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
        return "📊 Coverage (JavaScript/TypeScript)"

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
            ConfigField(
                name="coverage_command",
                field_type="string",
                default=DEFAULT_COVERAGE_COMMAND,
                description=("Command string (parsed via shlex) to generate coverage"),
            ),
            ConfigField(
                name="coverage_report_path",
                field_type="string",
                default=DEFAULT_COVERAGE_REPORT_PATH,
                description="Coverage report path relative to project root",
            ),
            ConfigField(
                name="coverage_format",
                field_type="string",
                default=DEFAULT_COVERAGE_FORMAT,
                description="Coverage report format: json-summary, lcov, or deno",
                choices=["json-summary", "lcov", "deno"],
            ),
        ]

    def init_config(self, project_root: str) -> dict[str, str]:
        """Discover a strong-evidence Deno coverage workflow for hybrid repos."""
        if not (
            self.has_package_json(project_root) and self.is_deno_project(project_root)
        ):
            return {}
        test_glob = self.discover_supabase_deno_test_glob(project_root)
        if test_glob is None:
            return {}
        return {
            "coverage_command": (
                "deno test --allow-all --no-check "
                f"--coverage=coverage/raw {test_glob}"
            ),
            "coverage_report_path": "coverage/raw",
            "coverage_format": "deno",
        }

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

        if self._should_install_dependencies():
            dep_result = self._ensure_dependencies(project_root, start_time)
            if dep_result is not None:
                return dep_result

        result = self._run_command(
            self._get_coverage_command(),
            cwd=project_root,
            timeout=300,
        )
        duration = time.time() - start_time

        coverage_data = self._parse_coverage_report(project_root)
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
            error="Coverage command failed",
            findings=[
                Finding(message="Coverage command failed", level=FindingLevel.ERROR)
            ],
        )

    def _get_coverage_command(self) -> List[str]:
        """Build the coverage command from config."""
        configured = self.config.get("coverage_command", DEFAULT_COVERAGE_COMMAND)
        return shlex.split(configured)

    def _get_coverage_report_path(self, project_root: str) -> Path:
        """Return the configured coverage report path."""
        rel_path = self.config.get("coverage_report_path", DEFAULT_COVERAGE_REPORT_PATH)
        return Path(project_root) / rel_path

    def _get_coverage_format(self) -> str:
        """Return the configured coverage report format."""
        value = self.config.get("coverage_format", DEFAULT_COVERAGE_FORMAT)
        return str(value).strip().lower()

    def _should_install_dependencies(self) -> bool:
        """Install node deps when the coverage command is npm/npx based."""
        cmd = self._get_coverage_command()
        return bool(cmd) and cmd[0] in ("npm", "npx")

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

    def _parse_coverage_report(self, project_root: str) -> Optional[Dict[str, Any]]:
        """Parse the configured coverage report, if available."""
        report_path = self._get_coverage_report_path(project_root)
        report_format = self._get_coverage_format()
        if not report_path.exists():
            return None
        if report_format == "json-summary":
            return self._parse_coverage_json(report_path)
        if report_format == "lcov":
            return self._parse_lcov_report(project_root, report_path)
        if report_format == "deno":
            return self._parse_deno_report(project_root, report_path)
        return None

    def _parse_coverage_json(self, report_path: Path) -> Optional[Dict[str, Any]]:
        """Parse a Jest-style coverage-summary.json report."""
        try:
            with report_path.open(encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def _parse_lcov_report(
        self, project_root: str, report_path: Path
    ) -> Optional[Dict[str, Any]]:
        """Convert an lcov file into the Jest-summary shape."""
        try:
            text = report_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
        return self._parse_lcov_text(project_root, text, Path(project_root))

    def _parse_deno_report(
        self, project_root: str, report_path: Path
    ) -> Optional[Dict[str, Any]]:
        """Convert a Deno raw coverage directory into the Jest-summary shape."""
        result = self._run_command(
            ["deno", "coverage", "--lcov", str(report_path)],
            cwd=project_root,
            timeout=300,
        )
        if not result.success:
            return None
        return self._parse_lcov_text(project_root, result.stdout, Path(project_root))

    def _parse_lcov_text(
        self, project_root: str, text: str, relative_base: Path
    ) -> Optional[Dict[str, Any]]:
        """Convert lcov text into the Jest-summary shape."""
        aggregate: Dict[str, Dict[str, int]] = {}
        current_file: Optional[str] = None
        root = Path(project_root).resolve()
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("SF:"):
                raw_path = line[3:]
                resolved = Path(raw_path)
                if not resolved.is_absolute():
                    resolved = (relative_base / raw_path).resolve()
                try:
                    rel = str(resolved.relative_to(root))
                except ValueError:
                    rel = raw_path.replace("\\", "/")
                current_file = rel
                aggregate.setdefault(current_file, {"total": 0, "covered": 0})
                continue

            if line.startswith("DA:") and current_file:
                parts = line[3:].split(",")
                if len(parts) < 2:
                    continue
                try:
                    hits = int(parts[1])
                except ValueError:
                    continue
                aggregate[current_file]["total"] += 1
                if hits > 0:
                    aggregate[current_file]["covered"] += 1
                continue

            if line == "end_of_record":
                current_file = None

        if not aggregate:
            return None
        total_lines = sum(stats["total"] for stats in aggregate.values())
        covered_lines = sum(stats["covered"] for stats in aggregate.values())
        summary: Dict[str, Any] = {
            "total": {
                "lines": {
                    "total": total_lines,
                    "covered": covered_lines,
                    "pct": (
                        (covered_lines / total_lines) * 100 if total_lines else 100.0
                    ),
                }
            }
        }
        for file_path, stats in aggregate.items():
            total = stats["total"]
            covered = stats["covered"]
            summary[file_path] = {
                "lines": {
                    "total": total,
                    "covered": covered,
                    "pct": (covered / total) * 100 if total else 100.0,
                }
            }
        return summary

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
