"""Dart format enforcement."""

import time
from pathlib import Path
from typing import Optional

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    Flaw,
    GateCategory,
    ToolContext,
    count_source_scope,
    find_tool,
)
from slopmop.checks.constants import NO_PUBSPEC_YAML_FOUND, TESTS_TIMED_OUT_MSG
from slopmop.checks.dart.common import find_pubspec_dirs
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    Finding,
    FindingLevel,
    ScopeInfo,
)


class DartFormatCheck(BaseCheck):
    """Check canonical Dart formatting across the repo."""

    tool_context = ToolContext.SM_TOOL
    role = CheckRole.FOUNDATION

    @property
    def name(self) -> str:
        return "dart-format-check"

    @property
    def display_name(self) -> str:
        return "🎨 Dart Format"

    @property
    def gate_description(self) -> str:
        return "🎨 Dart formatting via dart format --set-exit-if-changed"

    @property
    def category(self) -> GateCategory:
        return GateCategory.LAZINESS

    @property
    def flaw(self) -> Flaw:
        return Flaw.LAZINESS

    def is_applicable(self, project_root: str) -> bool:
        return bool(find_pubspec_dirs(project_root))

    def skip_reason(self, project_root: str) -> str:
        return NO_PUBSPEC_YAML_FOUND

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
        dart_path = find_tool("dart", project_root)
        if not dart_path:
            return self._create_result(
                status=CheckStatus.WARNED,
                duration=time.time() - start_time,
                error="dart not available",
                fix_suggestion="Install Dart SDK and ensure `dart` is on PATH",
                findings=[
                    Finding(message="dart not available", level=FindingLevel.WARNING)
                ],
            )

        result = self._run_command(
            [dart_path, "format", "--output=none", "--set-exit-if-changed", "."],
            cwd=project_root,
            timeout=120,
        )
        duration = time.time() - start_time
        if result.timed_out:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error=f"{TESTS_TIMED_OUT_MSG} (dart format)",
                findings=[
                    Finding(
                        message="dart format timed out",
                        level=FindingLevel.ERROR,
                    )
                ],
            )
        if not result.success:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error="Dart formatting drift detected",
                findings=[
                    Finding(
                        message="Dart formatting drift detected",
                        level=FindingLevel.ERROR,
                    )
                ],
                fix_suggestion=(
                    "Run `dart format .` and verify with: " + self.verify_command
                ),
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output="Dart formatting OK",
        )
