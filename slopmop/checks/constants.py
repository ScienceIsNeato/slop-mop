"""Shared constants and skip reason helpers for check modules.

Centralizes duplicate strings that appear across multiple checks,
flagged by the myopia:string-duplication gate.
"""

# Skip reasons shared across Python checks
SKIP_NOT_PYTHON_PROJECT = "Not a Python project"
SKIP_NO_PYTHON_FILES = "No Python files found"

# Shared across python/tests.py and javascript/tests.py — both use the
# same 300s timeout and both emit this into error= and Finding.message.
# Four occurrences before extraction tripped myopia:string-duplication.
TESTS_TIMED_OUT_MSG = "Tests timed out after 5 minutes"

# Sentinel substring returned by SubprocessRunner when a binary is not
# found (FileNotFoundError → returncode -1, stderr "Command not found: …").
# Used by dead_code, complexity, and static_analysis to detect missing tools.
COMMAND_NOT_FOUND = "Command not found"


def has_python_test_files(project_root: str, test_dirs: list[str]) -> bool:
    """Check whether any test_*.py files exist in the configured test dirs.

    Shared by PythonTestsCheck, PythonCoverageCheck, and
    PythonDiffCoverageCheck for is_applicable().
    """
    from pathlib import Path

    root = Path(project_root)
    return any(
        (root / d).exists() and any((root / d).rglob("test_*.py")) for d in test_dirs
    )


def skip_reason_no_test_files(test_dirs: list[str]) -> str:
    """Build skip reason for missing Python test files.

    Used by PythonTestsCheck, PythonCoverageCheck, PythonDiffCoverageCheck,
    and BogusTestsCheck.
    """
    return f"No Python test files (test_*.py) found in {test_dirs}"
