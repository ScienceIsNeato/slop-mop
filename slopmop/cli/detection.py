"""Project type detection for slop-mop CLI."""

import json
from pathlib import Path
from typing import Any, Dict


def _detect_python(project_root: Path) -> bool:
    """Check for Python project indicators."""
    py_indicators = ["setup.py", "pyproject.toml", "requirements.txt", "Pipfile"]
    for indicator in py_indicators:
        if (project_root / indicator).exists():
            return True
    return any(project_root.glob("**/*.py"))


def _detect_javascript(project_root: Path) -> bool:
    """Check for JavaScript project indicators."""
    js_indicators = ["package.json", "tsconfig.json"]
    for indicator in js_indicators:
        if (project_root / indicator).exists():
            return True
    return any(project_root.glob("**/*.js")) or any(project_root.glob("**/*.ts"))


def _detect_typescript(project_root: Path) -> bool:
    """Check specifically for TypeScript."""
    ts_indicators = ["tsconfig.json", "tsconfig.ci.json"]
    for indicator in ts_indicators:
        if (project_root / indicator).exists():
            return True
    return any(project_root.glob("**/*.ts"))


def _detect_test_dirs(project_root: Path) -> list[str]:
    """Find test directories."""
    test_dirs = []
    for test_dir in ["tests", "test", "spec", "__tests__"]:
        test_path = project_root / test_dir
        if test_path.is_dir():
            test_dirs.append(str(test_path.relative_to(project_root)))
    return test_dirs


def _detect_pytest(project_root: Path) -> bool:
    """Check for pytest configuration."""
    pyproject = project_root / "pyproject.toml"
    if pyproject.exists() and "pytest" in pyproject.read_text():
        return True

    setup_cfg = project_root / "setup.cfg"
    if setup_cfg.exists() and "pytest" in setup_cfg.read_text():
        return True

    return (project_root / "pytest.ini").exists() or (
        project_root / "conftest.py"
    ).exists()


def _detect_jest(project_root: Path) -> bool:
    """Check for Jest configuration."""
    package_json = project_root / "package.json"
    if not package_json.exists():
        return False

    try:
        pkg = json.loads(package_json.read_text())
        if "jest" in pkg.get("devDependencies", {}):
            return True
        if "jest" in pkg.get("dependencies", {}):
            return True
        if "test" in pkg.get("scripts", {}):
            if "jest" in pkg["scripts"]["test"]:
                return True
    except json.JSONDecodeError:
        pass
    return False


def _recommend_gates(detected: Dict[str, Any]) -> list[str]:
    """Determine recommended gates based on detection."""
    recommended = []
    if detected["has_python"]:
        recommended.extend(
            ["python-lint-format", "python-tests", "python-static-analysis"]
        )
        if detected["has_pytest"]:
            recommended.append("python-coverage")

    if detected["has_javascript"]:
        recommended.extend(["js-lint-format", "js-tests"])
        if detected["has_jest"]:
            recommended.append("js-coverage")
        if detected["has_typescript"]:
            recommended.append("javascript-types")

    return recommended


def _recommend_profile(detected: Dict[str, Any]) -> str:
    """Determine recommended profile based on detection."""
    if detected["has_python"] and detected["has_javascript"]:
        return "pr"
    elif detected["has_python"]:
        return "python"
    elif detected["has_javascript"]:
        return "javascript"
    return "commit"


def detect_project_type(project_root: Path) -> Dict[str, Any]:
    """Auto-detect project type and characteristics.

    Returns a dict with detected features:
    - has_python: bool
    - has_javascript: bool
    - has_typescript: bool
    - has_tests_dir: bool
    - has_pytest: bool
    - has_jest: bool
    - test_dirs: list of test directory paths
    - recommended_profile: str
    - recommended_gates: list of str
    """
    detected: Dict[str, Any] = {
        "has_python": _detect_python(project_root),
        "has_javascript": _detect_javascript(project_root),
        "has_typescript": _detect_typescript(project_root),
        "has_pytest": _detect_pytest(project_root),
        "has_jest": _detect_jest(project_root),
        "test_dirs": _detect_test_dirs(project_root),
    }

    detected["has_tests_dir"] = bool(detected["test_dirs"])
    detected["recommended_gates"] = _recommend_gates(detected)
    detected["recommended_profile"] = _recommend_profile(detected)

    return detected
