"""Python lint and format check using black, isort, and flake8.

This check:
1. Auto-fixes formatting with black
2. Auto-fixes import order with isort
3. Checks for critical lint errors with flake8
"""

import time
from typing import List, Optional

from slopbucket.checks.base import BaseCheck, PythonCheckMixin
from slopbucket.core.result import CheckResult, CheckStatus


class PythonLintFormatCheck(BaseCheck, PythonCheckMixin):
    """Python lint and format check.

    Runs:
    - black: Code formatting
    - isort: Import sorting
    - flake8: Critical lint errors (E9, F63, F7, F82, F401)

    Auto-fix is enabled by default for black and isort.
    """

    @property
    def name(self) -> str:
        return "python-lint-format"

    @property
    def display_name(self) -> str:
        return "🎨 Python Lint & Format (black, isort, flake8)"

    def is_applicable(self, project_root: str) -> bool:
        return self.is_python_project(project_root)

    def can_auto_fix(self) -> bool:
        return True

    def auto_fix(self, project_root: str) -> bool:
        """Auto-fix formatting issues with black and isort."""
        fixed = False

        # Run black
        result = self._run_command(
            ["black", "--line-length", "88", "."],
            cwd=project_root,
            timeout=60,
        )
        if result.success:
            fixed = True

        # Run isort
        result = self._run_command(
            ["isort", "--profile", "black", "."],
            cwd=project_root,
            timeout=60,
        )
        if result.success:
            fixed = True

        return fixed

    def run(self, project_root: str) -> CheckResult:
        """Run lint and format checks."""
        start_time = time.time()
        issues: List[str] = []
        output_parts: List[str] = []

        # Check 1: Black formatting
        black_result = self._check_black(project_root)
        if black_result:
            issues.append(black_result)
            output_parts.append(f"Black: {black_result}")
        else:
            output_parts.append("Black: ✅ Formatting OK")

        # Check 2: Isort imports
        isort_result = self._check_isort(project_root)
        if isort_result:
            issues.append(isort_result)
            output_parts.append(f"Isort: {isort_result}")
        else:
            output_parts.append("Isort: ✅ Import order OK")

        # Check 3: Flake8 critical errors
        flake8_result = self._check_flake8(project_root)
        if flake8_result:
            issues.append(flake8_result)
            output_parts.append(f"Flake8: {flake8_result}")
        else:
            output_parts.append("Flake8: ✅ No critical errors")

        duration = time.time() - start_time

        if issues:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output="\n".join(output_parts),
                error=f"{len(issues)} issue(s) found",
                fix_suggestion="Run: black . && isort . to auto-fix formatting",
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output="\n".join(output_parts),
        )

    def _check_black(self, project_root: str) -> Optional[str]:
        """Check black formatting."""
        result = self._run_command(
            ["black", "--check", "--line-length", "88", "."],
            cwd=project_root,
            timeout=60,
        )

        if not result.success:
            # Extract files that need formatting
            lines = result.output.split("\n")
            files = [l for l in lines if l.startswith("would reformat")]
            if files:
                return f"{len(files)} file(s) need formatting"
            return "Formatting check failed"
        return None

    def _check_isort(self, project_root: str) -> Optional[str]:
        """Check isort import order."""
        result = self._run_command(
            ["isort", "--check-only", "--profile", "black", "."],
            cwd=project_root,
            timeout=60,
        )

        if not result.success:
            return "Import order issues found"
        return None

    def _check_flake8(self, project_root: str) -> Optional[str]:
        """Check for critical flake8 errors."""
        # Only check critical errors: E9 (runtime), F63/F7/F82 (undefined), F401 (unused)
        result = self._run_command(
            [
                "flake8",
                "--select=E9,F63,F7,F82,F401",
                "--max-line-length=88",
                ".",
            ],
            cwd=project_root,
            timeout=60,
        )

        if not result.success and result.output.strip():
            lines = result.output.strip().split("\n")
            return f"{len(lines)} critical error(s):\n" + "\n".join(lines[:5])
        return None
