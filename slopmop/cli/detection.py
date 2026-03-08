"""Project type detection for slop-mop CLI."""

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
_INSTALL_FLUTTER = "Install Flutter SDK: https://docs.flutter.dev/get-started/install"

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
    # Dart/Flutter coverage gate
    ("flutter", "overconfidence:coverage-gaps.dart", _INSTALL_FLUTTER),
]

# Canonical language keys derived from scc --format json output.
_PYTHON_LANGS = {"python"}
_JAVASCRIPT_LANGS = {"javascript"}
_TYPESCRIPT_LANGS = {"typescript"}
_GO_LANGS = {"go"}
_RUST_LANGS = {"rust"}
_C_CPP_LANGS = {
    "c",
    "cheader",
    "cplusplus",
    "cplusplusheader",
    "objectivec",
    "objectivecplusplus",
}
_DART_LANGS = {"dart"}
_SCC_SUMMARY_ROWS = {"total", "totals", "sum", "header"}
_DETECTION_EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    ".pytest_cache",
    ".mypy_cache",
    ".slopmop",
}
_MAX_NESTED_SCAN_DEPTH = 4


def _normalize_language_key(name: str) -> str:
    """Normalize language names to stable keys for set membership checks.

    Example:
      "C++ Header" -> "cplusplusheader"
      "Objective-C" -> "objectivec"
    """
    lowered = name.strip().lower()
    # Preserve C/C++ distinctions before stripping punctuation.
    lowered = lowered.replace("++", "plusplus").replace("#", "sharp")
    normalized = "".join(ch for ch in lowered if ch.isalnum())
    return normalized


def _extract_scc_languages(payload: Any) -> Set[str]:
    """Extract normalized language keys from scc JSON output.

    scc's JSON schema has changed across versions; support both:
    - list of rows with "Name"/"Code"/...
    - dict shapes where language stats are keyed by language name
    """
    rows: List[Dict[str, Any]] = []
    languages: Set[str] = set()

    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
    elif isinstance(payload, dict):
        maybe_rows = payload.get("languages")
        if isinstance(maybe_rows, list):
            rows = [row for row in maybe_rows if isinstance(row, dict)]
        else:
            # Some versions key by language at top-level.
            for key, value in payload.items():
                if isinstance(key, str) and isinstance(value, dict):
                    norm = _normalize_language_key(key)
                    if norm and norm not in _SCC_SUMMARY_ROWS:
                        languages.add(norm)

    for row in rows:
        raw_name: Any = (
            row.get("Name")
            or row.get("name")
            or row.get("Language")
            or row.get("language")
        )
        if not isinstance(raw_name, str):
            continue
        norm = _normalize_language_key(raw_name)
        if not norm or norm in _SCC_SUMMARY_ROWS:
            continue
        languages.add(norm)

    return languages


def _detect_languages_with_scc(project_root: Path) -> Optional[Set[str]]:
    """Detect languages using local `scc` (no network).

    Returns:
      - set of normalized language keys when scc is available and output parses
      - None when scc is unavailable or output is unusable
    """
    scc_path = find_tool("scc", str(project_root))
    if not scc_path:
        return None

    try:
        result = subprocess.run(
            [scc_path, "--format", "json", "--no-cocomo", str(project_root)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    languages = _extract_scc_languages(payload)
    # Empty output behaves like unavailable output so manifest fallback still works.
    return languages or None


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


def _detect_python(
    project_root: Path, detected_languages: Optional[Set[str]] = None
) -> bool:
    """Check for Python project indicators.

    Manifest fallback.  We do NOT glob ``**/*.py`` because real-world
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
    if detected_languages is not None:
        return bool(detected_languages & _PYTHON_LANGS)

    py_indicators = ["setup.py", "pyproject.toml", "requirements.txt", "Pipfile"]
    return any((project_root / p).exists() for p in py_indicators)


def _detect_javascript(
    project_root: Path, detected_languages: Optional[Set[str]] = None
) -> bool:
    """Check for JavaScript project indicators.

    Manifest-only — same reasoning as ``_detect_python``.  Go repos
    (pocketbase) vendor an admin UI; Rust repos (zoxide) ship shell
    completion templates with ``.js`` extensions.  A ``**/*.js`` glob
    turns both into "JavaScript projects" and every JS gate then
    reports ``n/a (No package.json found)`` — which is the symptom
    telling you the detection was wrong in the first place.
    """
    if detected_languages is not None:
        return bool(detected_languages & (_JAVASCRIPT_LANGS | _TYPESCRIPT_LANGS))

    js_indicators = ["package.json", "tsconfig.json"]
    return any((project_root / p).exists() for p in js_indicators)


def _detect_typescript(
    project_root: Path, detected_languages: Optional[Set[str]] = None
) -> bool:
    """Check specifically for TypeScript."""
    if detected_languages is not None:
        return bool(detected_languages & _TYPESCRIPT_LANGS)

    ts_indicators = ["tsconfig.json", "tsconfig.ci.json"]
    return any((project_root / p).exists() for p in ts_indicators)


def _detect_go(
    project_root: Path, detected_languages: Optional[Set[str]] = None
) -> bool:
    """Check for Go project indicators."""
    if detected_languages is not None:
        return bool(detected_languages & _GO_LANGS)

    return (project_root / "go.mod").exists()


def _detect_rust(
    project_root: Path, detected_languages: Optional[Set[str]] = None
) -> bool:
    """Check for Rust project indicators."""
    if detected_languages is not None:
        return bool(detected_languages & _RUST_LANGS)

    return (project_root / "Cargo.toml").exists()


def _detect_c_cpp(
    project_root: Path, detected_languages: Optional[Set[str]] = None
) -> bool:
    """Check for C/C++ project indicators."""
    if detected_languages is not None:
        return bool(detected_languages & _C_CPP_LANGS)

    c_indicators = ["CMakeLists.txt", "Makefile", "configure.ac", "meson.build"]
    for indicator in c_indicators:
        if (project_root / indicator).exists():
            return True
    return False


def _detect_dart(
    project_root: Path, detected_languages: Optional[Set[str]] = None
) -> bool:
    """Check for Dart / Flutter project indicators."""
    if detected_languages is not None:
        return bool(detected_languages & _DART_LANGS)

    return (project_root / "pubspec.yaml").exists()


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
    names = {"tests", "test", "spec", "__tests__"}
    found: set[str] = set()
    for name in names:
        for path in project_root.rglob(name):
            if not path.is_dir():
                continue
            rel = path.relative_to(project_root)
            if len(rel.parts) > _MAX_NESTED_SCAN_DEPTH:
                continue
            if any(part in _DETECTION_EXCLUDED_DIRS for part in rel.parts):
                continue
            found.add(str(rel))
    return sorted(found)


def _detect_pytest(project_root: Path) -> bool:
    """Check for pytest configuration."""
    def _safe_contains(path: Path, needle: str) -> bool:
        try:
            return needle in path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False

    for path in project_root.rglob("pyproject.toml"):
        rel = path.relative_to(project_root)
        if len(rel.parts) > _MAX_NESTED_SCAN_DEPTH:
            continue
        if any(part in _DETECTION_EXCLUDED_DIRS for part in rel.parts):
            continue
        if _safe_contains(path, "pytest"):
            return True

    for path in project_root.rglob("setup.cfg"):
        rel = path.relative_to(project_root)
        if len(rel.parts) > _MAX_NESTED_SCAN_DEPTH:
            continue
        if any(part in _DETECTION_EXCLUDED_DIRS for part in rel.parts):
            continue
        if _safe_contains(path, "pytest"):
            return True

    for name in ("pytest.ini", "conftest.py"):
        for path in project_root.rglob(name):
            rel = path.relative_to(project_root)
            if len(rel.parts) > _MAX_NESTED_SCAN_DEPTH:
                continue
            if any(part in _DETECTION_EXCLUDED_DIRS for part in rel.parts):
                continue
            return True
    return False


def _detect_jest(project_root: Path) -> bool:
    """Check for Jest configuration."""
    for package_json in project_root.rglob("package.json"):
        rel = package_json.relative_to(project_root)
        if len(rel.parts) > _MAX_NESTED_SCAN_DEPTH:
            continue
        if any(part in _DETECTION_EXCLUDED_DIRS for part in rel.parts):
            continue
        try:
            pkg = json.loads(package_json.read_text(encoding="utf-8", errors="ignore"))
            if "jest" in pkg.get("devDependencies", {}):
                return True
            if "jest" in pkg.get("dependencies", {}):
                return True
            if "test" in pkg.get("scripts", {}):
                if "jest" in pkg["scripts"]["test"]:
                    return True
        except json.JSONDecodeError:
            continue
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

    if detected.get("has_dart"):
        recommended.extend(
            [
                "overconfidence:coverage-gaps.dart",
                "deceptiveness:bogus-tests.dart",
                "laziness:generated-artifacts.dart",
            ]
        )

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

    if detected.get("has_dart"):
        flutter_available = find_tool("flutter", str(project_root)) is not None
        dart_available = find_tool("dart", str(project_root)) is not None

        flutter_preflight = (
            "if flutter --version 2>&1 | grep -q "
            '"engine.stamp: Operation not permitted"; '
            'then echo "Skipping Flutter gate: SDK cache path not writable in this environment"; '
            "exit 0; fi; "
        )

        if flutter_available:
            gates.extend(
                [
                    {
                        "name": "flutter-analyze",
                        "description": "Run Flutter static analysis",
                        "category": "laziness",
                        "command": (
                            "sh -c 'set -e; "
                            + flutter_preflight
                            + 'pubspecs=$(find . -name pubspec.yaml -not -path "*/.*/*"); '
                            '[ -n "$pubspecs" ] || { echo "No pubspec.yaml found"; exit 1; }; '
                            "for pubspec in $pubspecs; do "
                            'dir=$(dirname "$pubspec"); '
                            'echo "==> flutter analyze ($dir)"; '
                            '(cd "$dir" && flutter analyze); '
                            "done'"
                        ),
                        "level": "swab",
                        "timeout": 300,
                    },
                    {
                        "name": "flutter-test",
                        "description": "Run Flutter tests",
                        "category": "overconfidence",
                        "command": (
                            "sh -c 'set -e; " + flutter_preflight + "ran=0; "
                            'pubspecs=$(find . -name pubspec.yaml -not -path "*/.*/*"); '
                            '[ -n "$pubspecs" ] || { echo "No pubspec.yaml found"; exit 1; }; '
                            "for pubspec in $pubspecs; do "
                            'dir=$(dirname "$pubspec"); '
                            'if [ -d "$dir/test" ]; then '
                            "ran=1; "
                            'echo "==> flutter test ($dir)"; '
                            '(cd "$dir" && flutter test); '
                            "fi; "
                            "done; "
                            '[ "$ran" -eq 1 ] || { echo "No Flutter test directories found"; exit 1; }'
                            "'"
                        ),
                        "level": "swab",
                        "timeout": 600,
                    },
                ]
            )

        if dart_available:
            gates.append(
                {
                    "name": "dart-format-check",
                    "description": "Check Dart formatting",
                    "category": "laziness",
                    "command": (
                        "sh -c 'set -e; "
                        + flutter_preflight
                        + "dart format --output=none --set-exit-if-changed .'"
                    ),
                    "level": "swab",
                    "timeout": 120,
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
    - has_dart: bool
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
    detected_languages = _detect_languages_with_scc(project_root)

    detected: Dict[str, Any] = {
        "has_python": _detect_python(project_root, detected_languages),
        "has_javascript": _detect_javascript(project_root, detected_languages),
        "has_typescript": _detect_typescript(project_root, detected_languages),
        "has_go": _detect_go(project_root, detected_languages),
        "has_rust": _detect_rust(project_root, detected_languages),
        "has_c_cpp": _detect_c_cpp(project_root, detected_languages),
        "has_dart": _detect_dart(project_root, detected_languages),
        "has_pytest": _detect_pytest(project_root),
        "has_jest": _detect_jest(project_root),
        "test_dirs": _detect_test_dirs(project_root),
        "package_manager": _detect_package_manager(project_root),
        "language_detector": "scc" if detected_languages is not None else "manifest",
        "detected_languages": sorted(detected_languages or []),
    }

    detected["has_tests_dir"] = bool(detected["test_dirs"])
    detected["recommended_gates"] = _recommend_gates(detected)
    detected["suggested_custom_gates"] = _suggest_custom_gates(detected, project_root)

    # Detect tool availability
    tool_info = _detect_tools(project_root)
    detected["available_tools"] = tool_info["available_tools"]
    detected["missing_tools"] = tool_info["missing_tools"]

    return detected
