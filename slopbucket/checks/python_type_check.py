"""
Python type checking — Mypy strict mode.

Validates type annotations across the source tree.
Excludes test directories (typically less strictly typed).
"""

import sys
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run


class PythonTypeCheck(BaseCheck):
    """Mypy strict type checking on source files."""

    @property
    def name(self) -> str:
        return "python-types"

    @property
    def description(self) -> str:
        return "Mypy strict type checking (source files)"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        import os

        base = working_dir or os.getcwd()

        # Find src/ directory
        src_dir = os.path.join(base, "src")
        if not os.path.isdir(src_dir):
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No src/ directory found.",
            )

        cmd = [
            sys.executable,
            "-m",
            "mypy",
            "src/",
            "--ignore-missing-imports",
            "--disallow-untyped-defs",
            "--explicit-package-bases",
            "--exclude",
            "tests/",
        ]
        result = run(cmd, cwd=working_dir)

        if result.success:
            return self._make_result(status=CheckStatus.PASSED, output="All types check out")

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout or result.stderr,
            fix_hint="Add type annotations to flagged functions. Run: mypy src/ --show-error-codes",
        )
