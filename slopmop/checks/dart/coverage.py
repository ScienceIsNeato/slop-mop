"""Dart/Flutter coverage threshold check."""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    RemediationChurn,
    ToolContext,
    count_source_scope,
    find_tool,
)
from slopmop.checks.constants import (
    NO_PUBSPEC_YAML_FOUND,
    coverage_below_threshold_message,
)
from slopmop.checks.dart.common import (
    FLUTTER_CACHE_NOT_WRITABLE,
    FLUTTER_CACHE_PERMISSION_ERROR,
    FLUTTER_INSTALL_FIX_SUGGESTION,
    FLUTTER_NOT_AVAILABLE,
    NO_FLUTTER_TEST_DIRECTORIES_FOUND,
    find_pubspec_dirs,
)
from slopmop.constants import COVERAGE_BELOW_THRESHOLD
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    Finding,
    FindingLevel,
    ScopeInfo,
)

DEFAULT_THRESHOLD = 80
MAX_FILES_TO_SHOW = 5


@dataclass
class _FileCoverage:
    total: int = 0
    covered: int = 0

    @property
    def pct(self) -> float:
        if self.total == 0:
            return 100.0
        return (self.covered / self.total) * 100.0


class DartCoverageCheck(BaseCheck):
    """Flutter test coverage gate (parses coverage/lcov.info)."""

    tool_context = ToolContext.SM_TOOL
    role = CheckRole.FOUNDATION
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_UNLIKELY

    @property
    def name(self) -> str:
        return "coverage-gaps.dart"

    @property
    def display_name(self) -> str:
        return "📊 Coverage (Dart/Flutter, lcov)"

    @property
    def gate_description(self) -> str:
        return "📊 Dart/Flutter coverage analysis from flutter test --coverage"

    @property
    def category(self) -> GateCategory:
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="threshold",
                field_type="integer",
                default=DEFAULT_THRESHOLD,
                description="Minimum line coverage percentage required",
                min_value=0,
                max_value=100,
                permissiveness="higher_is_stricter",
            )
        ]

    def is_applicable(self, project_root: str) -> bool:
        for package_dir in find_pubspec_dirs(project_root):
            if (package_dir / "test").is_dir():
                return True
        return False

    def skip_reason(self, project_root: str) -> str:
        if not find_pubspec_dirs(project_root):
            return NO_PUBSPEC_YAML_FOUND
        return NO_FLUTTER_TEST_DIRECTORIES_FOUND

    def measure_scope(self, project_root: str) -> Optional[ScopeInfo]:
        include_dirs = [
            str(pkg.relative_to(Path(project_root)))
            for pkg in find_pubspec_dirs(project_root)
        ]
        if not include_dirs:
            include_dirs = ["."]
        return count_source_scope(
            project_root, include_dirs=include_dirs, extensions={".dart"}
        )

    def _warn_flutter_missing(self, start_time: float) -> CheckResult:
        return self._create_result(
            status=CheckStatus.WARNED,
            duration=time.time() - start_time,
            error=FLUTTER_NOT_AVAILABLE,
            fix_suggestion=FLUTTER_INSTALL_FIX_SUGGESTION,
            findings=[
                Finding(
                    message=FLUTTER_NOT_AVAILABLE,
                    level=FindingLevel.WARNING,
                )
            ],
        )

    def _get_test_package_dirs(self, project_root: str) -> List[Path]:
        return [
            pkg for pkg in find_pubspec_dirs(project_root) if (pkg / "test").is_dir()
        ]

    def _run_coverage_for_package(
        self,
        project_root: str,
        package_dir: Path,
        flutter_path: str,
        aggregate: Dict[str, _FileCoverage],
        start_time: float,
    ) -> Optional[CheckResult]:
        result = self._run_command(
            [flutter_path, "test", "--coverage"],
            cwd=str(package_dir),
            timeout=900,
        )
        if not result.success or result.timed_out:
            if FLUTTER_CACHE_PERMISSION_ERROR in (result.output or ""):
                return self._create_result(
                    status=CheckStatus.SKIPPED,
                    duration=time.time() - start_time,
                    output=(
                        "Skipping coverage-gaps.dart: Flutter SDK cache path "
                        "is not writable in this environment."
                    ),
                    findings=[
                        Finding(
                            message=FLUTTER_CACHE_NOT_WRITABLE,
                            level=FindingLevel.WARNING,
                        )
                    ],
                )
            pkg_rel = str(package_dir.relative_to(Path(project_root)))
            message = f"flutter test failed in {pkg_rel}"
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=time.time() - start_time,
                error=message,
                output=result.output,
                findings=[Finding(message=message, level=FindingLevel.ERROR)],
                fix_suggestion=(
                    "Fix Flutter test failures and rerun coverage. "
                    f"Verify with: {self.verify_command}"
                ),
            )

        lcov_path = package_dir / "coverage" / "lcov.info"
        if not lcov_path.exists():
            pkg_rel = str(package_dir.relative_to(Path(project_root)))
            message = f"coverage/lcov.info not found in {pkg_rel}"
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=time.time() - start_time,
                error=message,
                findings=[Finding(message=message, level=FindingLevel.ERROR)],
            )

        self._merge_lcov(project_root, lcov_path, aggregate)
        return None

    def _build_failure_result(
        self,
        aggregate: Dict[str, _FileCoverage],
        threshold: int,
        coverage_pct: float,
        duration: float,
    ) -> CheckResult:
        low_files = sorted(
            (
                (file_path, stats)
                for file_path, stats in aggregate.items()
                if stats.pct < threshold
            ),
            key=lambda item: item[1].pct,
        )
        findings = [
            Finding(
                message=(
                    f"Coverage {stats.pct:.1f}% below {threshold}% "
                    f"({stats.covered}/{stats.total} lines)"
                ),
                file=file_path,
                level=FindingLevel.ERROR,
            )
            for file_path, stats in low_files
        ]

        lines = [
            coverage_below_threshold_message(coverage_pct, threshold),
            "",
            "Lowest coverage files:",
        ]
        for file_path, stats in low_files[:MAX_FILES_TO_SHOW]:
            lines.append(
                f"  {file_path}: {stats.pct:.1f}% ({stats.covered}/{stats.total})"
            )

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output="\n".join(lines),
            error=COVERAGE_BELOW_THRESHOLD,
            findings=findings
            or [
                Finding(
                    message=coverage_below_threshold_message(coverage_pct, threshold),
                    level=FindingLevel.ERROR,
                )
            ],
            fix_suggestion=(
                "Add or improve Flutter tests for the files listed above. "
                f"Verify with: {self.verify_command}"
            ),
        )

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()
        threshold = int(self.config.get("threshold", DEFAULT_THRESHOLD))

        flutter_path = find_tool("flutter", project_root)
        if not flutter_path:
            return self._warn_flutter_missing(start_time)

        package_dirs = self._get_test_package_dirs(project_root)
        if not package_dirs:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output=NO_FLUTTER_TEST_DIRECTORIES_FOUND,
            )

        aggregate: Dict[str, _FileCoverage] = {}
        for package_dir in package_dirs:
            package_error = self._run_coverage_for_package(
                project_root,
                package_dir,
                flutter_path,
                aggregate,
                start_time,
            )
            if package_error is not None:
                return package_error

        total_lines = sum(item.total for item in aggregate.values())
        covered_lines = sum(item.covered for item in aggregate.values())
        coverage_pct = (
            100.0 if total_lines == 0 else (covered_lines / total_lines) * 100.0
        )

        duration = time.time() - start_time
        if coverage_pct >= threshold:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=f"Coverage {coverage_pct:.1f}% meets threshold {threshold}%",
            )

        return self._build_failure_result(
            aggregate,
            threshold,
            coverage_pct,
            duration,
        )

    @staticmethod
    def _merge_lcov(
        project_root: str, lcov_path: Path, aggregate: Dict[str, _FileCoverage]
    ) -> None:
        current_file: Optional[str] = None
        root = Path(project_root).resolve()
        for raw_line in lcov_path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
            line = raw_line.strip()
            if line.startswith("SF:"):
                raw_path = line[3:]
                resolved = Path(raw_path)
                if not resolved.is_absolute():
                    resolved = (lcov_path.parent.parent / raw_path).resolve()
                try:
                    rel = str(resolved.relative_to(root))
                except ValueError:
                    rel = raw_path.replace("\\", "/")
                current_file = rel
                aggregate.setdefault(current_file, _FileCoverage())
                continue

            if line.startswith("DA:") and current_file:
                payload = line[3:]
                parts = payload.split(",")
                if len(parts) < 2:
                    continue
                try:
                    hits = int(parts[1])
                except ValueError:
                    continue
                aggregate[current_file].total += 1
                if hits > 0:
                    aggregate[current_file].covered += 1
                continue

            if line == "end_of_record":
                current_file = None
