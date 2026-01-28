"""
Python complexity check — Radon cyclomatic complexity.

Flags functions with complexity rank D or higher (>20).
Provides specific function names and their complexity scores
so agents can immediately identify what to refactor.
"""

import re
import sys
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run

# Max allowed complexity rank (A-C = pass, D-F = fail)
MAX_RANK = "C"
MAX_COMPLEXITY = 20


class PythonComplexityCheck(BaseCheck):
    """Radon cyclomatic complexity enforcement."""

    DEFAULT_DIRS = ["src", "tests", "scripts"]

    @property
    def name(self) -> str:
        return "python-complexity"

    @property
    def description(self) -> str:
        return f"Cyclomatic complexity (max rank {MAX_RANK}, complexity <{MAX_COMPLEXITY})"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        dirs = self._find_target_dirs(working_dir)
        if not dirs:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No Python directories found.",
            )

        # Run radon cc — show only D-F ranked functions
        cmd = [sys.executable, "-m", "radon", "cc", "--min", "D", "-s", "-a", "--md"] + dirs
        result = run(cmd, cwd=working_dir)

        # Parse output for violations
        violations = self._parse_violations(result.stdout)

        if not violations:
            return self._make_result(
                status=CheckStatus.PASSED,
                output="All functions within complexity limits",
            )

        detail = "Functions exceeding complexity limit:\n" + "\n".join(
            f"  {v}" for v in violations
        )
        return self._make_result(
            status=CheckStatus.FAILED,
            output=detail,
            fix_hint="Break complex functions into smaller helpers. Each function should do one thing.",
        )

    def _find_target_dirs(self, working_dir: Optional[str]) -> list:
        import os

        base = working_dir or os.getcwd()
        return [d for d in self.DEFAULT_DIRS if os.path.isdir(os.path.join(base, d))]

    def _parse_violations(self, output: str) -> list:
        """Extract D/E/F ranked functions from radon output."""
        violations = []
        for line in output.splitlines():
            # Radon format: "- function_name - D (25)"
            if re.search(r"\b[DEF]\b", line) and "(" in line:
                violations.append(line.strip())
        return violations
