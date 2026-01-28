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

    @property
    def name(self) -> str:
        return "python-complexity"

    @property
    def description(self) -> str:
        return (
            f"Cyclomatic complexity (max rank {MAX_RANK}, complexity <{MAX_COMPLEXITY})"
        )

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        dirs = self._find_target_dirs(working_dir)
        if not dirs:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No Python directories found.",
            )

        # Run radon cc — show only D-F ranked functions
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
        result = run(cmd, cwd=working_dir)

        # rc=127 or empty stdout with stderr indicates radon is not installed
        if result.returncode == 127 or (
            not result.success and not result.stdout.strip()
        ):
            return self._make_result(
                status=CheckStatus.ERROR,
                output=f"Radon not available: {result.stderr.strip()}",
                fix_hint="Install radon: pip install radon",
            )

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

        from slopbucket.checks.python_tests import _find_source_packages

        base = working_dir or os.getcwd()
        dirs = list(_find_source_packages(base))
        if os.path.isdir(os.path.join(base, "tests")):
            dirs.append("tests")
        return dirs

    def _parse_violations(self, output: str) -> list:
        """Extract D/E/F ranked functions from radon output."""
        violations = []
        for line in output.splitlines():
            # Radon format: "- function_name - D (25)"
            if re.search(r"\b[DEF]\b", line) and "(" in line:
                violations.append(line.strip())
        return violations
