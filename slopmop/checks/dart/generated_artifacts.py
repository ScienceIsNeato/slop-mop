"""Detect committed Flutter-generated artifacts in git-tracked files."""

import time
from pathlib import Path
from typing import List, Optional

from slopmop.checks.base import (
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    ToolContext,
)
from slopmop.checks.dart.common import (
    NO_PUBSPEC_FOUND,
    find_pubspec_dirs,
    unique_strings,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

MAX_SHOWN = 20


class DartGeneratedArtifactsCheck(BaseCheck):
    """Fail when Flutter build/tool artifacts are committed."""

    tool_context = ToolContext.SM_TOOL
    role = CheckRole.DIAGNOSTIC

    @property
    def name(self) -> str:
        return "generated-artifacts.dart"

    @property
    def display_name(self) -> str:
        return "🧱 Generated Artifacts (Dart/Flutter)"

    @property
    def gate_description(self) -> str:
        return "🧱 Detects committed Flutter build/tool artifacts"

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
                name="exclude_paths",
                field_type="string[]",
                default=[],
                description="Relative path prefixes to ignore",
                permissiveness="fewer_is_stricter",
            )
        ]

    def is_applicable(self, project_root: str) -> bool:
        return bool(find_pubspec_dirs(project_root))

    def skip_reason(self, project_root: str) -> str:
        return NO_PUBSPEC_FOUND

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()
        root = Path(project_root).resolve()
        package_prefixes = [
            "." if pkg == root else str(pkg.relative_to(root)).replace("\\", "/")
            for pkg in find_pubspec_dirs(project_root)
        ]

        git_result = self._run_command(
            ["git", "ls-files"], cwd=project_root, timeout=30
        )
        duration = time.time() - start_time
        if not git_result.success:
            return self._create_result(
                status=CheckStatus.WARNED,
                duration=duration,
                error="Could not enumerate tracked files via git ls-files",
                output=git_result.output,
                findings=[
                    Finding(
                        message="Could not enumerate tracked files via git ls-files",
                        level=FindingLevel.WARNING,
                    )
                ],
            )

        tracked_paths = [
            line.strip().replace("\\", "/")
            for line in git_result.stdout.splitlines()
            if line.strip()
        ]
        exclude_prefixes = {
            str(p).strip("/").replace("\\", "/")
            for p in self.config.get("exclude_paths", [])
            if isinstance(p, str) and p.strip()
        }

        violations = unique_strings(
            path
            for path in tracked_paths
            if self._is_dart_artifact(path, package_prefixes, exclude_prefixes)
        )
        if not violations:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output="No committed Flutter generated artifacts found",
            )

        lines = ["Committed Flutter generated artifacts found:", ""]
        lines.extend(f"  {path}" for path in violations[:MAX_SHOWN])
        if len(violations) > MAX_SHOWN:
            lines.append(f"  ... and {len(violations) - MAX_SHOWN} more")

        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output="\n".join(lines),
            error=f"{len(violations)} generated artifact file(s) committed",
            findings=[
                Finding(
                    message="Generated Flutter artifact committed",
                    file=path,
                    level=FindingLevel.ERROR,
                )
                for path in violations
            ],
            fix_suggestion=(
                "Remove generated artifacts from git and add/update .gitignore. "
                "Verify with: " + self.verify_command
            ),
        )

    @staticmethod
    def _is_dart_artifact(
        tracked_path: str,
        package_prefixes: List[str],
        exclude_prefixes: set[str],
    ) -> bool:
        path = tracked_path.strip("/").replace("\\", "/")
        if any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in exclude_prefixes
        ):
            return False

        rel = DartGeneratedArtifactsCheck._path_within_package(path, package_prefixes)
        if rel is None:
            return False

        rel_parts = Path(rel).parts
        if ".dart_tool" in rel_parts:
            return True
        if rel.startswith("ios/Flutter/ephemeral/"):
            return True
        if rel.startswith("android/.gradle/"):
            return True
        if rel_parts and rel_parts[0] == "build":
            return True
        if Path(rel).name in {
            ".flutter-plugins",
            ".flutter-plugins-dependencies",
            "flutter_export_environment.sh",
        }:
            return True
        return False

    @staticmethod
    def _path_within_package(path: str, package_prefixes: List[str]) -> Optional[str]:
        for prefix in package_prefixes:
            if prefix == ".":
                return path
            if path == prefix:
                return ""
            if path.startswith(prefix + "/"):
                return path[len(prefix) + 1 :]
        return None
