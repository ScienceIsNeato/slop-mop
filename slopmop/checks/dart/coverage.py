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
    ToolContext,
    count_source_scope,
    find_tool,
)
from slopmop.checks.constants import coverage_below_threshold_message
from slopmop.checks.dart.common import (
    NO_PUBSPEC_FOUND,
    VERIFY_WITH_PREFIX,
    find_pubspec_dirs,
)
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    Finding,
    FindingLevel,
    ScopeInfo,
)

DEFAULT_THRESHOLD = 80
MAX_FILES_TO_SHOW = 5
_FLUTTER_CACHE_PERMISSION_ERROR = "engine.stamp: Operation not permitted"
_NO_DART_TEST_DIRS = "No Flutter test directories found (expected package/test/)"
_FLUTTER_CACHE_NOT_WRITABLE_OUTPUT = (
    "Skipping coverage-gaps.dart: Flutter SDK cache path "
    "is not writable in this environment."
)
_FLUTTER_CACHE_NOT_WRITABLE_MESSAGE = (
    "Flutter SDK cache path is not writable in this environment"
)


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
        return bool(find_pubspec_dirs(project_root))

    def skip_reason(self, project_root: str) -> str:
        if not find_pubspec_dirs(project_root):
            return NO_PUBSPEC_FOUND
        return "Dart coverage check not applicable"

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

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()
        threshold = int(self.config.get("threshold", DEFAULT_THRESHOLD))

        flutter_path = find_tool("flutter", project_root)
        if not flutter_path:
            return self._flutter_missing_result(start_time)

        package_dirs = [
            pkg for pkg in find_pubspec_dirs(project_root) if (pkg / "test").is_dir()
        ]
        if not package_dirs:
            return self._no_test_dirs_result(start_time)

        aggregate: Dict[str, _FileCoverage] = {}
        for package_dir in package_dirs:
            package_result = self._collect_package_coverage(
                project_root=project_root,
                start_time=start_time,
                flutter_path=flutter_path,
                package_dir=package_dir,
                aggregate=aggregate,
            )
            if package_result is not None:
                return package_result

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
        below_threshold_msg = coverage_below_threshold_message(coverage_pct, threshold)

        lines = [
            below_threshold_msg,
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
            error=below_threshold_msg,
            findings=findings
            or [
                Finding(
                    message=below_threshold_msg,
                    level=FindingLevel.ERROR,
                )
            ],
            fix_suggestion=(
                "Add or improve Flutter tests for the files listed above. "
                f"{VERIFY_WITH_PREFIX}{self.verify_command}"
            ),
        )

    def _flutter_missing_result(self, start_time: float) -> CheckResult:
        return self._create_result(
            status=CheckStatus.WARNED,
            duration=time.time() - start_time,
            error="flutter not available",
            fix_suggestion="Install Flutter SDK and ensure `flutter` is on PATH",
            findings=[
                Finding(
                    message="flutter not available",
                    level=FindingLevel.WARNING,
                )
            ],
        )

    def _no_test_dirs_result(self, start_time: float) -> CheckResult:
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=time.time() - start_time,
            output=_NO_DART_TEST_DIRS,
            error=_NO_DART_TEST_DIRS,
            fix_suggestion=(
                "Add Flutter tests under package test/ directories. "
                f"{VERIFY_WITH_PREFIX}{self.verify_command}"
            ),
            findings=[Finding(message=_NO_DART_TEST_DIRS, level=FindingLevel.ERROR)],
        )

    def _collect_package_coverage(
        self,
        project_root: str,
        start_time: float,
        flutter_path: str,
        package_dir: Path,
        aggregate: Dict[str, _FileCoverage],
    ) -> Optional[CheckResult]:
        result = self._run_command(
            [flutter_path, "test", "--coverage"],
            cwd=str(package_dir),
            timeout=900,
        )
        if not result.success or result.timed_out:
            return self._package_test_failure_result(
                project_root, start_time, package_dir, result.output
            )

        lcov_path = package_dir / "coverage" / "lcov.info"
        if not lcov_path.exists():
            return self._missing_lcov_result(project_root, start_time, package_dir)

        self._merge_lcov(project_root, lcov_path, aggregate)
        return None

    def _package_test_failure_result(
        self,
        project_root: str,
        start_time: float,
        package_dir: Path,
        output: str,
    ) -> CheckResult:
        if _FLUTTER_CACHE_PERMISSION_ERROR in (output or ""):
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output=_FLUTTER_CACHE_NOT_WRITABLE_OUTPUT,
                findings=[
                    Finding(
                        message=_FLUTTER_CACHE_NOT_WRITABLE_MESSAGE,
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
            output=output,
            findings=[Finding(message=message, level=FindingLevel.ERROR)],
            fix_suggestion=(
                "Fix Flutter test failures and rerun coverage. "
                f"{VERIFY_WITH_PREFIX}{self.verify_command}"
            ),
        )

    def _missing_lcov_result(
        self, project_root: str, start_time: float, package_dir: Path
    ) -> CheckResult:
        pkg_rel = str(package_dir.relative_to(Path(project_root)))
        message = f"coverage/lcov.info not found in {pkg_rel}"
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=time.time() - start_time,
            error=message,
            findings=[Finding(message=message, level=FindingLevel.ERROR)],
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
