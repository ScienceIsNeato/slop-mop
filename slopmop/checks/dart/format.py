"""Dart format enforcement."""

import time
from pathlib import Path
from typing import List, Optional

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    Flaw,
    GateCategory,
    Requirement,
    Requirements,
    ToolContext,
    count_source_scope,
    find_tool,
)
from slopmop.checks.constants import NO_PUBSPEC_YAML_FOUND
from slopmop.checks.dart.common import (
    DART_INSTALL_HINT,
    find_pubspec_dirs,
    format_package_label,
)
from slopmop.checks.timeouts import SLOW_TOOL_TIMEOUT
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

    def requirements(self) -> Requirements:
        # Optional: a missing dart WARNs (degrades), it does not fail
        # the gate. ``version=None`` — the dart toolchain version is
        # environment-specific, not something slop-mop pins.
        return Requirements(
            items=(
                Requirement(
                    kind="system",
                    name="dart",
                    install_hint=DART_INSTALL_HINT,
                    optional=True,
                    reason="formats Dart code",
                ),
            )
        )

    role = CheckRole.FOUNDATION

    @property
    def name(self) -> str:
        return "sloppy-formatting.dart"

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

        package_dirs = find_pubspec_dirs(project_root)
        outputs: List[str] = []
        for package_dir in package_dirs:
            label = format_package_label(project_root, package_dir)
            result = self._run_command(
                [dart_path, "format", "--output=none", "--set-exit-if-changed", "."],
                cwd=str(package_dir),
                timeout=SLOW_TOOL_TIMEOUT,
            )
            if result.timed_out:
                return self._create_result(
                    status=CheckStatus.FAILED,
                    duration=time.time() - start_time,
                    output=result.output,
                    error=f"{label}: dart format timed out after {SLOW_TOOL_TIMEOUT}s",
                    findings=[
                        Finding(
                            message=f"{label}: dart format timed out",
                            level=FindingLevel.ERROR,
                        )
                    ],
                )
            if not result.success:
                return self._create_result(
                    status=CheckStatus.FAILED,
                    duration=time.time() - start_time,
                    output=result.output,
                    error=f"{label}: Dart formatting drift detected",
                    findings=[
                        Finding(
                            message=f"{label}: Dart formatting drift detected",
                            level=FindingLevel.ERROR,
                        )
                    ],
                    fix_suggestion=(
                        f"Run `dart format .` in {label} and verify with: "
                        + self.verify_command
                    ),
                )
            outputs.append(f"{label}: formatting OK")

        duration = time.time() - start_time
        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output="\n".join(outputs) or "Dart formatting OK",
        )
