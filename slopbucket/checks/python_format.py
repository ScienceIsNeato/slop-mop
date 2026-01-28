"""
Python formatting check — Black + isort + autoflake.

Strategy: Auto-fix first, then validate. This reduces noise for agents:
the check only fails if auto-fix itself cannot resolve the issue.
"""

import sys
from typing import Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import SubprocessResult, run


class PythonFormatCheck(BaseCheck):
    """Validates Python code formatting via Black, isort, and autoflake."""

    @property
    def name(self) -> str:
        return "python-format"

    @property
    def description(self) -> str:
        return "Python formatting: Black, isort, autoflake (auto-fix applied)"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        dirs = self._find_target_dirs(working_dir)
        if not dirs:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No Python directories found to format.",
            )

        issues = []

        # 1. autoflake — remove unused imports (non-blocking, best-effort)
        self._run_autoflake(dirs, working_dir)

        # 2. black — format code
        black_result = self._run_black(dirs, working_dir)
        if not black_result.success:
            issues.append(("black", black_result.output))

        # 3. isort — sort imports
        isort_result = self._run_isort(dirs, working_dir)
        if not isort_result.success:
            issues.append(("isort", isort_result.output))

        # 4. Validation pass — ensure fixes were applied
        validate_result = self._validate(dirs, working_dir)
        if validate_result:
            issues.extend(validate_result)

        if issues:
            detail = "\n".join(f"  [{tool}] {msg}" for tool, msg in issues)
            return self._make_result(
                status=CheckStatus.FAILED,
                output=detail,
                fix_hint="Run: black . && isort --profile black . && autoflake --in-place --remove-all-unused-imports -r .",
            )

        return self._make_result(status=CheckStatus.PASSED, output="All formatting OK")

    def _find_target_dirs(self, working_dir: Optional[str]) -> list:
        """Find Python directories to format via auto-discovery."""
        import os

        from slopbucket.checks.python_tests import _find_source_packages

        base = working_dir or os.getcwd()
        dirs = list(_find_source_packages(base))
        # Always include tests/ if present
        if os.path.isdir(os.path.join(base, "tests")):
            dirs.append("tests")
        return dirs

    def _run_autoflake(self, dirs: list, working_dir: Optional[str]) -> None:
        """Run autoflake to remove unused imports (best-effort, non-blocking)."""
        # Use `python -m autoflake --version` — `which` misses module-only installs
        probe = run([sys.executable, "-m", "autoflake", "--version"], cwd=working_dir)
        if not probe.success:
            return
        cmd = [
            sys.executable,
            "-m",
            "autoflake",
            "--in-place",
            "--remove-all-unused-imports",
            "--recursive",
        ] + dirs
        run(cmd, cwd=working_dir)

    def _run_black(self, dirs: list, working_dir: Optional[str]) -> SubprocessResult:
        """Run black with auto-fix."""
        cmd = [sys.executable, "-m", "black", "--line-length", "88"] + dirs
        return run(cmd, cwd=working_dir)

    def _run_isort(self, dirs: list, working_dir: Optional[str]) -> SubprocessResult:
        """Run isort with auto-fix."""
        cmd = [sys.executable, "-m", "isort", "--profile", "black"] + dirs
        return run(cmd, cwd=working_dir)

    def _validate(self, dirs: list, working_dir: Optional[str]) -> list:
        """Verify formatting is clean after auto-fix attempt."""
        issues = []

        # Check black
        cmd = [sys.executable, "-m", "black", "--check", "--line-length", "88"] + dirs
        result = run(cmd, cwd=working_dir)
        if not result.success:
            issues.append(("black-check", result.stderr or result.stdout))

        # Check isort
        cmd = [
            sys.executable,
            "-m",
            "isort",
            "--check-only",
            "--diff",
            "--profile",
            "black",
        ] + dirs
        result = run(cmd, cwd=working_dir)
        if not result.success:
            issues.append(("isort-check", result.stdout or result.stderr))

        return issues
