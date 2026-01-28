"""
Python type checking — Mypy strict mode.

Validates type annotations across the source tree.
Auto-discovers source packages (src/ or top-level packages).
Excludes test directories (typically less strictly typed).
"""

import sys
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.checks.python_tests import _find_source_packages
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

        source_packages = _find_source_packages(base)
        if not source_packages:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No source packages found (looked for src/ or packages with __init__.py).",
            )

        cmd = (
            [
                sys.executable,
                "-m",
                "mypy",
            ]
            + source_packages
            + [
                "--ignore-missing-imports",
                "--disallow-untyped-defs",
                "--explicit-package-bases",
                "--exclude",
                "tests/",
            ]
        )
        result = run(cmd, cwd=working_dir, timeout=120)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED, output="All types check out"
            )

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout or result.stderr,
            fix_hint="Add type annotations to flagged functions. Run: mypy <package>/ --show-error-codes",
        )
