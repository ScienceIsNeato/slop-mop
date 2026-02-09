"""Shared constants and skip reason helpers for check modules.

Centralizes duplicate strings that appear across multiple checks,
flagged by the quality:string-duplication gate.
"""

# Skip reasons shared across Python checks
SKIP_NOT_PYTHON_PROJECT = "Not a Python project"
SKIP_NO_PYTHON_FILES = "No Python files found"


def skip_reason_no_test_files(test_dirs: list[str]) -> str:
    """Build skip reason for missing Python test files.

    Used by PythonTestsCheck, PythonCoverageCheck, PythonDiffCoverageCheck,
    and BogusTestsCheck.
    """
    return f"No Python test files (test_*.py) found in {test_dirs}"
