"""Cyclomatic complexity check using radon.

Flags functions with complexity rank D or higher (>20).
Provides specific function names and their complexity scores
so agents can immediately identify what to refactor.

Note: This is a cross-cutting quality check. While it uses radon
(a Python tool), complexity is a universal code quality concern.
"""

import os
import re
import sys
import time
from typing import List

from slopmop.checks.base import (
    BaseCheck,
    ConfigField,
    GateCategory,
)
from slopmop.core.result import CheckResult, CheckStatus

MAX_RANK = "C"
MAX_COMPLEXITY = 20


class ComplexityCheck(BaseCheck):
    """Radon cyclomatic complexity enforcement.

    Uses 'src_dirs' from config, or defaults to scanning Python files
    in project root.
    """

    @property
    def name(self) -> str:
        return "complexity"

    @property
    def display_name(self) -> str:
        return f"🌀 Complexity (max rank {MAX_RANK})"

    @property
    def category(self) -> GateCategory:
        return GateCategory.QUALITY

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="max_rank",
                field_type="string",
                default="C",
                description="Maximum complexity rank (A-F)",
                choices=["A", "B", "C", "D", "E", "F"],
            ),
            ConfigField(
                name="max_complexity",
                field_type="integer",
                default=15,
                description="Maximum cyclomatic complexity score",
            ),
            ConfigField(
                name="src_dirs",
                field_type="string[]",
                default=[],
                description="Directories to scan for complexity (empty = project root)",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        """Check if there are Python files to analyze."""
        from pathlib import Path

        root = Path(project_root)
        return any(root.rglob("*.py"))

    def _get_target_dirs(self, project_root: str) -> List[str]:
        """Get directories to check from config, with sensible fallbacks."""
        # Use configured src_dirs if available
        configured = self.config.get("src_dirs", [])
        if configured:
            return [
                d for d in configured if os.path.isdir(os.path.join(project_root, d))
            ]
        # Fallback: check project root for .py files
        return ["."]

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()
        dirs = self._get_target_dirs(project_root)

        if not dirs:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="No src_dirs configured and no Python files found.",
            )

        cmd = [
            sys.executable,
            "-m",
            "radon",
            "cc",
            "--min",
            "D",
            "-s",
            "-a",
            "--md",
        ] + dirs
        result = self._run_command(cmd, cwd=project_root, timeout=120)
        duration = time.time() - start_time

        if result.returncode == 127:
            return self._create_result(
                status=CheckStatus.ERROR,
                duration=duration,
                error="Radon not available",
                fix_suggestion="Install radon: pip install radon",
            )

        violations = self._parse_violations(result.output)
        if not violations:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=duration,
                output="All functions within complexity limits",
            )

        detail = "Functions exceeding complexity:\n" + "\n".join(
            f"  {v}" for v in violations
        )
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error=f"{len(violations)} function(s) exceed limit",
            fix_suggestion="Break complex functions into smaller helpers.",
        )

    def _parse_violations(self, output: str) -> List[str]:
        violations = []
        for line in output.splitlines():
            if re.search(r"\b[DEF]\b", line) and "(" in line:
                violations.append(line.strip())
        return violations
