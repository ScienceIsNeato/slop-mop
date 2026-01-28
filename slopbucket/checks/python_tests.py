"""
Python test runner — Pytest with coverage generation.

Executes unit and integration tests. Generates coverage.xml
for downstream coverage checks. Auto-discovers test and source
directories so it works in any repo layout.
"""

import sys
from typing import List, Optional

from slopbucket.base_check import BaseCheck
from slopbucket.result import CheckResult, CheckStatus
from slopbucket.subprocess_guard import run


def _find_source_packages(base: str) -> List[str]:
    """Auto-discover Python source packages for coverage.

    Looks for: src/, or any top-level directory containing __init__.py.
    Excludes tests, venv, node_modules, archives.
    """
    import os

    exclude = {"tests", "venv", ".venv", "node_modules", "archives", ".git", "docs"}

    # Prefer explicit src/ if it exists
    if os.path.isdir(os.path.join(base, "src")):
        return ["src"]

    # Otherwise find packages with __init__.py
    packages = []
    for entry in os.listdir(base):
        path = os.path.join(base, entry)
        if entry.startswith(".") or entry in exclude:
            continue
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "__init__.py")):
            packages.append(entry)

    return packages


class PythonTestsCheck(BaseCheck):
    """Pytest test runner with coverage instrumentation."""

    @property
    def name(self) -> str:
        return "python-tests"

    @property
    def description(self) -> str:
        return "Pytest unit + integration tests with coverage generation"

    def execute(self, working_dir: Optional[str] = None) -> CheckResult:
        import os

        base = working_dir or os.getcwd()

        # Discover test directories
        test_dirs: List[str] = []
        for candidate in ["tests/unit", "tests/integration", "tests"]:
            path = os.path.join(base, candidate)
            if os.path.isdir(path):
                test_dirs.append(candidate)
                if candidate == "tests":
                    break  # Don't add subdirs if parent exists alone

        if not test_dirs:
            return self._make_result(
                status=CheckStatus.SKIPPED,
                output="No test directories found.",
            )

        # Discover source packages for coverage
        source_packages = _find_source_packages(base)

        cmd = [sys.executable, "-m", "pytest"] + test_dirs + ["--tb=short", "-v"]

        # Add coverage flags only if we found source packages
        if source_packages:
            for pkg in source_packages:
                cmd.extend(["--cov", pkg])
            cmd.extend(["--cov-report=term-missing", "--cov-report=xml:coverage.xml"])

        result = run(cmd, cwd=working_dir, timeout=600)

        if result.success:
            return self._make_result(
                status=CheckStatus.PASSED,
                output=self._extract_summary(result.stdout),
            )

        return self._make_result(
            status=CheckStatus.FAILED,
            output=result.stdout + result.stderr,
            fix_hint="Fix failing tests. Run: pytest tests/ -v --tb=long for detailed output.",
        )

    def _extract_summary(self, output: str) -> str:
        """Extract the pytest summary line from output."""
        for line in reversed(output.splitlines()):
            if "passed" in line or "failed" in line or "error" in line:
                return line.strip()
        return "Tests completed"
