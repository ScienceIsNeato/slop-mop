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

# Shared no-tests and language literals reused across checks.
PYTHON_NO_TESTS_FIX_PREFIX = "Add Python tests (test_*.py or *_test.py) in configured "
JS_NO_TESTS_FOUND_EXPECTED = (
    "No JavaScript/TypeScript tests found "
    "(expected test dirs or *.test.* / *.spec.* files)"
)
JS_NO_TESTS_FOUND_JEST = (
    "No JavaScript/TypeScript tests found " "(Jest reported no matching tests)"
)
NO_PUBSPEC_YAML_FOUND = "No pubspec.yaml found"
TAUTOLOGICAL_ASSERTION_PREFIX = "tautological assertion"


def tautological_assertion_reason(tautology: str) -> str:
    """Build a consistent tautological-assertion finding reason."""
    return f"{TAUTOLOGICAL_ASSERTION_PREFIX}: {tautology}"


def has_python_test_files(project_root: str, test_dirs: list[str]) -> bool:
    """Check whether Python test files exist in the configured test dirs.

    Shared by PythonTestsCheck, PythonCoverageCheck, and
    PythonDiffCoverageCheck for is_applicable().
    """
    from pathlib import Path

    root = Path(project_root)
    patterns = ("test_*.py", "*_test.py")
    for test_dir in test_dirs:
        base = root / test_dir
        if not base.exists():
            continue
        for pattern in patterns:
            if any(base.rglob(pattern)):
                return True
    return False


def skip_reason_no_test_files(test_dirs: list[str]) -> str:
    """Build skip reason for missing Python test files.

    Used by PythonTestsCheck, PythonCoverageCheck, PythonDiffCoverageCheck,
    and BogusTestsCheck.
    """
    return f"No Python test files (test_*.py or *_test.py) found in {test_dirs}"


def python_no_tests_fix_suggestion(test_dirs: list[str], verify_command: str) -> str:
    """Build fix suggestion for missing Python tests."""
    return (
        f"{PYTHON_NO_TESTS_FIX_PREFIX}test_dirs={test_dirs}. "
        f"Verify with: {verify_command}"
    )


def js_no_tests_fix_suggestion(verify_command: str) -> str:
    """Build fix suggestion for missing JavaScript/TypeScript tests."""
    return (
        "Add JS/TS tests (for example under test/, tests/, __tests__, "
        f"or as *.test.ts/*.spec.js). Verify with: {verify_command}"
    )


def coverage_below_threshold_message(coverage_pct: float, threshold: int) -> str:
    """Build a normalized below-threshold coverage message."""
    return f"Coverage {coverage_pct:.1f}% below threshold {threshold}%"
