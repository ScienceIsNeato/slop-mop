"""Project type detection for slop-mop CLI."""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from slopmop.checks.base import find_tool

# Tools required by specific checks: (tool_name, check_name, install_command)
# Used during `sm init` to auto-disable checks whose tools aren't available.
# find_tool() resolves these via project venv → .venv → VIRTUAL_ENV → PATH.
# When sm is installed via pipx, most tools are bundled and found via PATH.
REQUIRED_TOOLS: List[Tuple[str, str, str]] = [
    # Lint & format (sloppy-formatting.py gate)
    ("black", "laziness:sloppy-formatting.py", "pip install black  # in your venv"),
    ("isort", "laziness:sloppy-formatting.py", "pip install isort  # in your venv"),
    (
        "autoflake",
        "laziness:sloppy-formatting.py",
        "pip install autoflake  # in your venv",
    ),
    ("flake8", "laziness:sloppy-formatting.py", "pip install flake8  # in your venv"),
    # Static analysis & types
    ("vulture", "laziness:dead-code.py", "pip install vulture  # in your venv"),
    (
        "pyright",
        "overconfidence:type-blindness.py",
        "pip install pyright  # in your venv",
    ),
    # Security scanning
    (
        "bandit",
        "myopia:vulnerability-blindness.py",
        "pip install bandit  # in your venv",
    ),
    (
        "semgrep",
        "myopia:vulnerability-blindness.py",
        "pip install semgrep  # in your venv",
    ),
    (
        "detect-secrets",
        "myopia:vulnerability-blindness.py",
        "pip install detect-secrets  # in your venv",
    ),
    ("pip-audit", "myopia:dependency-risk.py", "pip install pip-audit  # in your venv"),
    # Complexity scanning (not bundled — install system-wide or in venv)
    (
        "radon",
        "laziness:complexity-creep.py",
        "pip install radon  # in your venv or: brew install radon",
    ),
]


def _detect_tools(project_root: Path) -> Dict[str, Any]:
    """Detect which required tools are available.

    Uses find_tool() from base.py which handles venv/bin, .venv/bin,
    Windows Scripts paths, and falls back to shutil.which().

    Returns:
        Dict with:
        - available_tools: list of tool names that are installed
        - missing_tools: list of (tool_name, check_name, install_command) for missing tools
    """
    available: List[str] = []
    missing: List[Tuple[str, str, str]] = []

    for tool_name, check_name, install_cmd in REQUIRED_TOOLS:
        found = find_tool(tool_name, str(project_root))
        if found:
            available.append(tool_name)
        else:
            missing.append((tool_name, check_name, install_cmd))

    return {
        "available_tools": available,
        "missing_tools": missing,
    }


def _detect_python(project_root: Path) -> bool:
    """Check for Python project indicators.

    Manifest-only.  We do NOT glob ``**/*.py`` because real-world
    polyglot repos routinely ship stray Python utility scripts:

    * curl/             — test-case generators in tests/*.py
    * pocketbase/       — doc-build scripts
    * zoxide/           — benchmark harness

    Globbing those causes ``sm init`` to light up the whole Python gate
    tree, and then every Python gate sits at n/a (no-applicable-source)
    forever.  That's noise, not signal.  If somebody's running a Python
    project with zero manifest files in 2025 they can flip the gates on
    by hand.
    """
    py_indicators = ["setup.py", "pyproject.toml", "requirements.txt", "Pipfile"]
    return any((project_root / p).exists() for p in py_indicators)


def _detect_javascript(project_root: Path) -> bool:
    """Check for JavaScript project indicators.

    Manifest-only — same reasoning as ``_detect_python``.  Go repos
    (pocketbase) vendor an admin UI; Rust repos (zoxide) ship shell
    completion templates with ``.js`` extensions.  A ``**/*.js`` glob
    turns both into "JavaScript projects" and every JS gate then
    reports ``n/a (No package.json found)`` — which is the symptom
    telling you the detection was wrong in the first place.
    """
    js_indicators = ["package.json", "tsconfig.json"]
    return any((project_root / p).exists() for p in js_indicators)


def _detect_typescript(project_root: Path) -> bool:
    """Check specifically for TypeScript (manifest-only)."""
    ts_indicators = ["tsconfig.json", "tsconfig.ci.json"]
    return any((project_root / p).exists() for p in ts_indicators)


def _detect_go(project_root: Path) -> bool:
    """Check for Go project indicators.

    ``go.mod`` is definitive — every modern Go module has one at its
    root.  We do NOT glob for ``*.go`` because many polyglot repos
    (e.g. next.js) vendor Go snippets in example dirs.
    """
    return (project_root / "go.mod").exists()


def _detect_rust(project_root: Path) -> bool:
    """Check for Rust project indicators.

    ``Cargo.toml`` at the root is definitive for a Rust crate/workspace.
    """
    return (project_root / "Cargo.toml").exists()


def _detect_c(project_root: Path) -> bool:
    """Check for C/C++ project indicators.

    C projects are heterogeneous; look for the common build-system
    anchors.  This will also catch C++ — that's fine for scaffolding
    purposes (the scaffolded gate is ``make check`` either way).
    """
    anchors = ["configure.ac", "configure", "CMakeLists.txt", "meson.build"]
    if any((project_root / a).exists() for a in anchors):
        return True
    # Plain-Makefile project with .c sources at top level
    if (project_root / "Makefile").exists():
        return any(project_root.glob("*.c")) or any(project_root.glob("src/*.c"))
    return False


def _detect_test_dirs(project_root: Path) -> list[str]:
    """Find test directories."""
    test_dirs: list[str] = []
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
    recommended: list[str] = []
    if detected["has_python"]:
        recommended.extend(
            [
                "laziness:sloppy-formatting.py",
                "overconfidence:untested-code.py",
                "overconfidence:missing-annotations.py",
            ]
        )
        if detected["has_pytest"]:
            recommended.append("overconfidence:coverage-gaps.py")

    if detected["has_javascript"]:
        recommended.extend(
            ["laziness:sloppy-formatting.js", "overconfidence:untested-code.js"]
        )
        if detected["has_jest"]:
            recommended.append("overconfidence:coverage-gaps.js")
        if detected["has_typescript"]:
            recommended.append("overconfidence:type-blindness.js")

    return recommended


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
    - recommended_gates: list of str
    - available_tools: list of str
    - missing_tools: list of (tool_name, check_name, install_command)
    """
    detected: Dict[str, Any] = {
        "has_python": _detect_python(project_root),
        "has_javascript": _detect_javascript(project_root),
        "has_typescript": _detect_typescript(project_root),
        "has_go": _detect_go(project_root),
        "has_rust": _detect_rust(project_root),
        "has_c": _detect_c(project_root),
        "has_pytest": _detect_pytest(project_root),
        "has_jest": _detect_jest(project_root),
        "test_dirs": _detect_test_dirs(project_root),
    }

    detected["has_tests_dir"] = bool(detected["test_dirs"])
    detected["recommended_gates"] = _recommend_gates(detected)

    # Detect tool availability
    tool_info = _detect_tools(project_root)
    detected["available_tools"] = tool_info["available_tools"]
    detected["missing_tools"] = tool_info["missing_tools"]

    return detected
