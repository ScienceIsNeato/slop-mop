"""Flutter static analysis gate."""

import time
from pathlib import Path
from typing import List, Optional

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    Flaw,
    GateCategory,
    ToolContext,
    count_source_scope,
    find_tool,
)
from slopmop.checks.constants import NO_PUBSPEC_YAML_FOUND
from slopmop.checks.dart.common import (
    FLUTTER_CACHE_PERMISSION_ERROR,
    find_pubspec_dirs,
    format_package_label,
)
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    Finding,
    FindingLevel,
    ScopeInfo,
)


class FlutterAnalyzeCheck(BaseCheck):
    """Run flutter analyze across all discovered pubspec packages."""

    tool_context = ToolContext.SM_TOOL
    role = CheckRole.FOUNDATION

    @property
    def name(self) -> str:
        return "flutter-analyze"

    @property
    def display_name(self) -> str:
        return "🧪 Flutter Analyze"

    @property
    def gate_description(self) -> str:
        return "🧪 Flutter static analysis across discovered packages"

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
        flutter_path = find_tool("flutter", project_root)
        if not flutter_path:
            return self._create_result(
                status=CheckStatus.WARNED,
                duration=time.time() - start_time,
                error="flutter not available",
                fix_suggestion="Install Flutter SDK and ensure `flutter` is on PATH",
                findings=[
                    Finding(message="flutter not available", level=FindingLevel.WARNING)
                ],
            )

        package_dirs = find_pubspec_dirs(project_root)
        outputs: List[str] = []
        for package_dir in package_dirs:
            label = format_package_label(project_root, package_dir)
            result = self._run_command(
                [flutter_path, "analyze"],
                cwd=str(package_dir),
                timeout=300,
            )
            if FLUTTER_CACHE_PERMISSION_ERROR in (result.output or ""):
                return self._create_result(
                    status=CheckStatus.SKIPPED,
                    duration=time.time() - start_time,
                    output=(
                        "Skipping flutter-analyze: Flutter SDK cache path is not writable "
                        "in this environment."
                    ),
                    findings=[
                        Finding(
                            message=(
                                "Flutter SDK cache path is not writable in this environment"
                            ),
                            level=FindingLevel.WARNING,
                        )
                    ],
                )
            if result.timed_out or not result.success:
                return self._create_result(
                    status=CheckStatus.FAILED,
                    duration=time.time() - start_time,
                    error=f"flutter analyze failed in {label}",
                    output=result.output,
                    findings=[
                        Finding(
                            message=f"flutter analyze failed in {label}",
                            level=FindingLevel.ERROR,
                        )
                    ],
                    fix_suggestion=(
                        "Fix Flutter analyzer issues and verify with: "
                        + self.verify_command
                    ),
                )
            outputs.append(f"{label}: analyze clean")

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=time.time() - start_time,
            output="\n".join(outputs) or "flutter analyze clean",
        )
