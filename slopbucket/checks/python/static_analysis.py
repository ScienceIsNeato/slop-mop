"""Python static analysis check using mypy."""

import time

from slopbucket.checks.base import BaseCheck, PythonCheckMixin
from slopbucket.core.result import CheckResult, CheckStatus


class PythonStaticAnalysisCheck(BaseCheck, PythonCheckMixin):
    """Python static analysis check.

    Runs mypy for type checking.
    """

    @property
    def name(self) -> str:
        return "python-static-analysis"

    @property
    def display_name(self) -> str:
        return "🔍 Python Static Analysis (mypy)"

    def is_applicable(self, project_root: str) -> bool:
        return self.is_python_project(project_root)

    def run(self, project_root: str) -> CheckResult:
        """Run mypy type checking."""
        start_time = time.time()

        # Detect source directories to check
        import os

        source_dirs = []
        for name in ["src", "slopbucket", "lib"]:
            path = os.path.join(project_root, name)
            if os.path.isdir(path):
                source_dirs.append(name)

        # If no standard source dirs found, check for Python packages
        if not source_dirs:
            for entry in os.listdir(project_root):
                entry_path = os.path.join(project_root, entry)
                if (
                    os.path.isdir(entry_path)
                    and os.path.exists(os.path.join(entry_path, "__init__.py"))
                    and entry not in ("tests", "test", "venv", ".venv", "build", "dist")
                ):
                    source_dirs.append(entry)

        if not source_dirs:
            source_dirs = ["."]

        result = self._run_command(
            [
                "mypy",
                *source_dirs,
                "--ignore-missing-imports",
                "--no-strict-optional",
            ],
            cwd=project_root,
            timeout=120,
        )

        duration = time.time() - start_time

        if result.timed_out:
            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error="Type checking timed out after 2 minutes",
            )

        if not result.success:
            # Count errors
            lines = result.output.split("\n")
            error_lines = [l for l in lines if ": error:" in l]

            return self._create_result(
                status=CheckStatus.FAILED,
                duration=duration,
                output=result.output,
                error=f"{len(error_lines)} type error(s) found",
                fix_suggestion="Fix type annotations or add # type: ignore comments",
            )

        return self._create_result(
            status=CheckStatus.PASSED,
            duration=duration,
            output=result.output,
        )
