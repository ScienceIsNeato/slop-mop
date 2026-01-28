"""Python cyclomatic complexity check using radon.

Flags functions with complexity rank D or higher (>20).
Provides specific function names and their complexity scores
so agents can immediately identify what to refactor.
"""

import os
import re
import sys
import time
from typing import List

from slopbucket.checks.base import BaseCheck, PythonCheckMixin
from slopbucket.core.result import CheckResult, CheckStatus

MAX_RANK = "C"
MAX_COMPLEXITY = 20


class PythonComplexityCheck(BaseCheck, PythonCheckMixin):
    """Radon cyclomatic complexity enforcement."""

    @property
    def name(self) -> str:
        return "python-complexity"

    @property
    def display_name(self) -> str:
        return f"🌀 Python Complexity (max rank {MAX_RANK})"

    def is_applicable(self, project_root: str) -> bool:
        return self.is_python_project(project_root)

    def run(self, project_root: str) -> CheckResult:
        start_time = time.time()
        dirs = self._find_target_dirs(project_root)

        if not dirs:
            return self._create_result(
                status=CheckStatus.SKIPPED,
                duration=time.time() - start_time,
                output="No Python directories found.",
            )

        cmd = [sys.executable, "-m", "radon", "cc", "--min", "D", "-s", "-a", "--md"] + dirs
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

        detail = "Functions exceeding complexity:\n" + "\n".join(f"  {v}" for v in violations)
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=duration,
            output=detail,
            error=f"{len(violations)} function(s) exceed limit",
            fix_suggestion="Break complex functions into smaller helpers.",
        )

    def _find_target_dirs(self, project_root: str) -> List[str]:
        dirs = []
        for name in ["src", "slopbucket", "lib"]:
            if os.path.isdir(os.path.join(project_root, name)):
                dirs.append(name)
        if os.path.isdir(os.path.join(project_root, "tests")):
            dirs.append("tests")
        return dirs

    def _parse_violations(self, output: str) -> List[str]:
        violations = []
        for line in output.splitlines():
            if re.search(r"\b[DEF]\b", line) and "(" in line:
                violations.append(line.strip())
        return violations
