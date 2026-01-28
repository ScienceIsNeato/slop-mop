"""
Python linting check — Flake8 critical errors only.

Only flags issues that indicate broken code, not style preferences:
E9  — syntax errors
F63 — invalid assertions
F7  — syntax errors in type comments
F82 — undefined names
F401 — unused imports (caught post-autoflake)
"""

import sys
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run


class PythonLintCheck(BaseCheck):
    """Flake8 check scoped to critical errors only."""

    CRITICAL_CODES = ["E9", "F63", "F7", "F82", "F401"]

    @property
    def name(self) -> str:
        return "python-lint"

    @property
    def description(self) -> str:
        return "Flake8 critical errors (syntax, undefined names, unused imports)"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        dirs = self._find_target_dirs(working_dir)
        if not dirs:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No Python directories found.",
            )

        select_codes = ",".join(self.CRITICAL_CODES)
        cmd = [sys.executable, "-m", "flake8", "--select", select_codes] + dirs
        result = run(cmd, cwd=working_dir)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED, output="No critical lint errors"
            )

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout or result.stderr,
            fix_hint="Fix the errors shown above. E9/F7 = syntax errors, F82 = undefined name, F401 = unused import.",
        )

    def _find_target_dirs(self, working_dir: Optional[str]) -> list:
        import os

        from slopbucket.checks.python_tests import _find_source_packages

        base = working_dir or os.getcwd()
        dirs = list(_find_source_packages(base))
        if os.path.isdir(os.path.join(base, "tests")):
            dirs.append("tests")
        return dirs
