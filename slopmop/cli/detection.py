"""Project type detection for slop-mop CLI."""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from slopmop.checks.base import find_tool

# Tools required by specific checks: (tool_name, check_name, install_command)
# Used during `sm init` to auto-disable checks whose tools aren't available.
# find_tool() resolves these via project venv → .venv → VIRTUAL_ENV → PATH.
#
# Install commands reference pyproject.toml optional-dependency groups:
#   lint      — black, isort, autoflake, flake8, ruff
#   typing    — mypy, pyright
#   analysis  — vulture, radon
#   security  — bandit, semgrep, detect-secrets, pip-audit
#   testing   — pytest, pytest-cov, diff-cover
#   all       — everything above

# Install-command constants (one source of truth for each extra group)
_INSTALL_LINT = "pipx install slopmop[lint]"
_INSTALL_TYPING = "pipx install slopmop[typing]"
_INSTALL_ANALYSIS = "pipx install slopmop[analysis]"
_INSTALL_SECURITY = "pipx install slopmop[security]"

REQUIRED_TOOLS: List[Tuple[str, str, str]] = [
    # Lint & format (sloppy-formatting.py gate) → [lint] extra
    ("black", "laziness:sloppy-formatting.py", _INSTALL_LINT),
    ("isort", "laziness:sloppy-formatting.py", _INSTALL_LINT),
    ("autoflake", "laziness:sloppy-formatting.py", _INSTALL_LINT),
    ("flake8", "laziness:sloppy-formatting.py", _INSTALL_LINT),
    # Static analysis → [analysis] extra
    ("vulture", "laziness:dead-code.py", _INSTALL_ANALYSIS),
    # Type checking → [typing] extra
    ("mypy", "overconfidence:missing-annotations.py", _INSTALL_TYPING),
    ("pyright", "overconfidence:type-blindness.py", _INSTALL_TYPING),
    # Security scanning → [security] extra
    ("bandit", "myopia:vulnerability-blindness.py", _INSTALL_SECURITY),
    ("semgrep", "myopia:vulnerability-blindness.py", _INSTALL_SECURITY),
    ("detect-secrets", "myopia:vulnerability-blindness.py", _INSTALL_SECURITY),
    ("pip-audit", "myopia:dependency-risk.py", _INSTALL_SECURITY),
    # Complexity scanning → [analysis] extra
    ("radon", "laziness:complexity-creep.py", _INSTALL_ANALYSIS),
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
    """Check for Go project indicators."""
    return (project_root / "go.mod").exists()


def _detect_rust(project_root: Path) -> bool:
    """Check for Rust project indicators."""
    return (project_root / "Cargo.toml").exists()


def _detect_c_cpp(project_root: Path) -> bool:
    """Check for C/C++ project indicators."""
    c_indicators = ["CMakeLists.txt", "Makefile", "configure.ac", "meson.build"]
    for indicator in c_indicators:
        if (project_root / indicator).exists():
            return True
    return False


# this is a duplicate - need to keep just one version of this method
def _detect_package_manager(project_root: Path) -> str:
    """Detect which package manager the JS project uses.

    Returns "pnpm", "yarn", or "npm" (default).

    NOTE: A near-identical helper lives in ``mixins.JavaScriptCheckMixin``.
    Both should converge on a shared utility (see slopmop/utils/) in a
    follow-up PR to avoid drift.
    """
    if (project_root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project_root / "yarn.lock").exists():
        return "yarn"
    return "npm"


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


def _suggest_custom_gates(
    detected: Dict[str, Any], project_root: Path
) -> List[Dict[str, Any]]:
    """Suggest custom gates for detected non-Python/JS languages."""
    gates: List[Dict[str, Any]] = []

    if detected.get("has_go"):
        gates.extend(
            [
                {
                    "name": "go-vet",
                    "description": "Run go vet for suspicious constructs",
                    "category": "laziness",
                    "command": "go vet ./...",
                    "level": "swab",
                    "timeout": 120,
                },
                {
                    "name": "go-test",
                    "description": "Run Go tests",
                    "category": "overconfidence",
                    "command": "go test ./...",
                    "level": "swab",
                    "timeout": 300,
                },
                {
                    "name": "go-fmt-check",
                    "description": "Check Go formatting (gofmt)",
                    "category": "laziness",
                    "command": 'test -z "$(gofmt -l .)"',
                    "level": "swab",
                    "timeout": 30,
                },
            ]
        )

    if detected.get("has_rust"):
        gates.extend(
            [
                {
                    "name": "cargo-check",
                    "description": "Run cargo check for compilation errors",
                    "category": "overconfidence",
                    "command": "cargo check 2>&1",
                    "level": "swab",
                    "timeout": 300,
                },
                {
                    "name": "cargo-clippy",
                    "description": "Run clippy lints",
                    "category": "laziness",
                    "command": "cargo clippy -- -D warnings 2>&1",
                    "level": "swab",
                    "timeout": 300,
                },
                {
                    "name": "cargo-test",
                    "description": "Run Rust tests",
                    "category": "overconfidence",
                    "command": "cargo test 2>&1",
                    "level": "scour",
                    "timeout": 600,
                },
                {
                    "name": "cargo-fmt-check",
                    "description": "Check Rust formatting",
                    "category": "laziness",
                    "command": "cargo fmt -- --check 2>&1",
                    "level": "swab",
                    "timeout": 30,
                },
            ]
        )

    if detected.get("has_c_cpp") and (project_root / "Makefile").exists():
        # Only suggest make-based gates when a Makefile is actually present;
        # without one the command will just fail with "No targets specified".
        gates.append(
            {
                "name": "build-check",
                "description": "Verify project builds cleanly",
                "category": "overconfidence",
                "command": "make -j$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4) 2>&1",
                "level": "scour",
                "timeout": 600,
            }
        )

    return gates


def detect_project_type(project_root: Path) -> Dict[str, Any]:
    """Auto-detect project type and characteristics.

    Returns a dict with detected features:
    - has_python: bool
    - has_javascript: bool
    - has_typescript: bool
    - has_go: bool
    - has_rust: bool
    - has_c_cpp: bool
    - has_tests_dir: bool
    - has_pytest: bool
    - has_jest: bool
    - test_dirs: list of test directory paths
    - recommended_gates: list of str
    - available_tools: list of str
    - missing_tools: list of (tool_name, check_name, install_command)
    - package_manager: str ("npm", "pnpm", or "yarn")
    - suggested_custom_gates: list of custom gate defs
    """
    detected: Dict[str, Any] = {
        "has_python": _detect_python(project_root),
        "has_javascript": _detect_javascript(project_root),
        "has_typescript": _detect_typescript(project_root),
        "has_go": _detect_go(project_root),
        "has_rust": _detect_rust(project_root),
        "has_c_cpp": _detect_c_cpp(project_root),
        "has_pytest": _detect_pytest(project_root),
        "has_jest": _detect_jest(project_root),
        "test_dirs": _detect_test_dirs(project_root),
        "package_manager": _detect_package_manager(project_root),
    }

    detected["has_tests_dir"] = bool(detected["test_dirs"])
    detected["recommended_gates"] = _recommend_gates(detected)
    detected["suggested_custom_gates"] = _suggest_custom_gates(detected, project_root)

    # Detect tool availability
    tool_info = _detect_tools(project_root)
    detected["available_tools"] = tool_info["available_tools"]
    detected["missing_tools"] = tool_info["missing_tools"]

    return detected
