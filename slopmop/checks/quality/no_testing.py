"""Detect repositories with source code but no test signal."""

from __future__ import annotations

import fnmatch
import os
import time
from pathlib import Path
from typing import List, Set

from slopmop.checks.base import (
    SCOPE_EXCLUDED_DIRS,
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    ToolContext,
    count_source_scope,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel, ScopeInfo

_SOURCE_EXTENSIONS: Set[str] = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".dart",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".rb",
    ".php",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".cs",
    ".scala",
    ".sh",
    ".bash",
}

_DEFAULT_TEST_DIRS = ["test", "tests", "spec", "__tests__", "e2e", "integration"]
_DEFAULT_TEST_FILE_GLOBS = [
    "test_*.py",
    "*_test.py",
    "*.test.js",
    "*.spec.js",
    "*.test.ts",
    "*.spec.ts",
    "*.test.jsx",
    "*.spec.jsx",
    "*.test.tsx",
    "*.spec.tsx",
    "*_test.dart",
    "*_spec.dart",
    "*_test.go",
]
_DEFAULT_TEST_CONFIG_FILES = [
    "pytest.ini",
    "conftest.py",
    "jest.config.js",
    "jest.config.cjs",
    "jest.config.mjs",
    "jest.config.ts",
    "vitest.config.js",
    "vitest.config.mjs",
    "vitest.config.ts",
]


class NoTestingCheck(BaseCheck):
    """Fail when source code exists but no tests are present."""

    tool_context = ToolContext.PURE
    role = CheckRole.FOUNDATION

    @property
    def name(self) -> str:
        return "literally-no-testing"

    @property
    def display_name(self) -> str:
        return "🧪 Literally No Testing"

    @property
    def gate_description(self) -> str:
        return "🧪 Fails if source code exists but no tests/config are detected"

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
                name="include_dirs",
                field_type="string[]",
                default=["."],
                description="Directories to scan (relative to project root)",
                permissiveness="more_is_stricter",
            ),
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description="Additional directories to skip while scanning",
                permissiveness="fewer_is_stricter",
            ),
            ConfigField(
                name="test_dirs",
                field_type="string[]",
                default=_DEFAULT_TEST_DIRS.copy(),
                description="Directory names treated as test roots",
            ),
            ConfigField(
                name="test_file_globs",
                field_type="string[]",
                default=_DEFAULT_TEST_FILE_GLOBS.copy(),
                description="Filename/path globs that count as tests",
            ),
            ConfigField(
                name="test_config_files",
                field_type="string[]",
                default=_DEFAULT_TEST_CONFIG_FILES.copy(),
                description="Config files that imply test setup exists",
            ),
            ConfigField(
                name="max_files",
                field_type="integer",
                default=50000,
                description="Bail-out limit for very large repositories",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        root = Path(project_root)
        include_dirs = self.config.get("include_dirs", ["."])
        excluded = self._excluded_dirs()
        max_files = int(self.config.get("max_files") or 50000)

        files_scanned = 0
        for rel_path in self._iter_repo_files(root, include_dirs, excluded):
            files_scanned += 1
            if files_scanned > max_files:
                return True
            if rel_path.suffix in _SOURCE_EXTENSIONS:
                return True
        return False

    def skip_reason(self, project_root: str) -> str:
        return "No source files found in supported languages"

    def measure_scope(self, project_root: str) -> ScopeInfo | None:
        include_dirs = self.config.get("include_dirs", ["."])
        excluded = set(self.config.get("exclude_dirs", []))
        return count_source_scope(
            project_root,
            include_dirs=include_dirs,
            extensions=_SOURCE_EXTENSIONS,
            exclude_dirs=excluded,
        )

    def run(self, project_root: str) -> CheckResult:
        start = time.time()
        root = Path(project_root)
        include_dirs = self.config.get("include_dirs", ["."])
        excluded = self._excluded_dirs()
        test_dirs = set(self.config.get("test_dirs") or _DEFAULT_TEST_DIRS)
        test_globs = list(self.config.get("test_file_globs") or _DEFAULT_TEST_FILE_GLOBS)
        test_configs = set(
            self.config.get("test_config_files") or _DEFAULT_TEST_CONFIG_FILES
        )
        max_files = int(self.config.get("max_files") or 50000)

        source_files: List[str] = []
        test_signals: List[str] = []
        files_scanned = 0

        for rel_path in self._iter_repo_files(root, include_dirs, excluded):
            files_scanned += 1
            if files_scanned > max_files:
                return self._create_result(
                    status=CheckStatus.WARNED,
                    duration=time.time() - start,
                    output=(
                        f"Scanned {max_files} files and stopped. "
                        "Narrow scope with include_dirs/exclude_dirs."
                    ),
                    findings=[
                        Finding(
                            message=(
                                f"Scan stopped after {max_files} files; "
                                "narrow include_dirs/exclude_dirs"
                            ),
                            level=FindingLevel.WARNING,
                        )
                    ],
                )

            rel_str = str(rel_path)
            rel_name = rel_path.name
            parts = set(rel_path.parts)

            if rel_name in test_configs:
                test_signals.append(rel_str)

            if rel_path.suffix in _SOURCE_EXTENSIONS:
                source_files.append(rel_str)
                if parts & test_dirs:
                    test_signals.append(rel_str)
                elif any(
                    fnmatch.fnmatch(rel_name, pattern)
                    or fnmatch.fnmatch(rel_str, pattern)
                    for pattern in test_globs
                ):
                    test_signals.append(rel_str)

        duration = time.time() - start

        if not source_files:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=duration,
                output="No source files found in supported languages",
            )

        unique_signals = sorted(set(test_signals))
        if unique_signals:
            preview = ", ".join(unique_signals[:3])
            more = "" if len(unique_signals) <= 3 else f", +{len(unique_signals) - 3} more"
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output=(
                    f"Detected {len(unique_signals)} test signal(s) across "
                    f"{len(source_files)} source file(s): {preview}{more}"
                ),
            )

        sample_sources = ", ".join(source_files[:5])
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=(
                f"No test files/config detected while scanning {len(source_files)} "
                f"source file(s). Example sources: {sample_sources}"
            ),
            error="Repository has source code but no test signal",
            findings=[
                Finding(
                    message="No tests detected for repository source files",
                    level=FindingLevel.ERROR,
                )
            ],
            fix_suggestion=(
                "Add at least one real test suite (e.g., tests/, *.test.ts, *_test.py), "
                "or disable overconfidence:literally-no-testing if this repository is "
                f"intentionally testless. Verify with: {self.verify_command}"
            ),
        )

    def _excluded_dirs(self) -> Set[str]:
        user_excludes = set(self.config.get("exclude_dirs") or [])
        return SCOPE_EXCLUDED_DIRS | user_excludes

    @staticmethod
    def _iter_repo_files(
        root: Path, include_dirs: List[str], excluded_dirs: Set[str]
    ):
        for include in include_dirs:
            base = root / include
            if not base.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                rel_dir = Path(dirpath).relative_to(root)
                if set(rel_dir.parts) & excluded_dirs:
                    dirnames[:] = []
                    continue
                dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
                for filename in filenames:
                    rel_path = (rel_dir / filename) if str(rel_dir) != "." else Path(filename)
                    if set(rel_path.parts) & excluded_dirs:
                        continue
                    yield rel_path
