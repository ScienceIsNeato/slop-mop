"""Language-specific check mixins — Python and JavaScript project helpers.

Split out of ``base.py`` when that file hit the 1000-line code-sprawl
gate.  These classes are pure mixins: they have no meaningful
``__init__``, expect to be mixed into a ``BaseCheck`` subclass, and
reach for ``self._create_result`` / ``self.config`` which the host
class provides.  They live in their own file because venv detection
and npm-lockfile sniffing have nothing to do with the abstract gate
contract — they were just squatting in ``base.py`` by historical
accident.

``PythonCheckMixin`` handles the venv-resolution dance: figuring out
which ``python`` to invoke when the project has its own ``.venv`` but
slop-mop was installed via pipx and has a DIFFERENT python with the
bundled scanners.  The resolution order (project venv → VIRTUAL_ENV →
sys.executable → PATH) and the warn-once-per-root caching are the
bits that actually matter.

``JavaScriptCheckMixin`` does the pnpm/yarn/npm lockfile detection
plus the ``.npmrc`` parsing for ``legacy-peer-deps`` — the kind of
thing every JS gate needs and nobody wants to write twice.
"""

import logging
import os
import shutil
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Optional, cast

from slopmop.checks.base import count_source_scope
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    Finding,
    FindingLevel,
    ScopeInfo,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Free-function project introspection helpers
#
# These are the pure, side-effect-free cores of the mixin methods below.
# The mixins wrap them to participate in the ``BaseCheck`` contract
# (cached warnings, ``self.config`` access, result construction).  Other
# callers — notably ``sm doctor`` — need the same resolution logic
# without the gate scaffolding or the warn-once caching.
# ---------------------------------------------------------------------------

# Returned by resolve_project_python().  String constants rather than an
# Enum: callers treat this as opaque display/JSON data and Enum would
# just add ceremony.
PYTHON_SOURCE_PROJECT_VENV = "project_venv"
PYTHON_SOURCE_VIRTUAL_ENV = "virtual_env"
PYTHON_SOURCE_SYS_EXECUTABLE = "sys_executable"
PYTHON_SOURCE_PATH = "system_path"
PYTHON_SOURCE_NOT_FOUND = "not_found"


def _find_python_in_venv(venv_path: Path) -> Optional[str]:
    """Return the ``python`` inside *venv_path* or None if none exists."""
    for subpath in ["bin/python", "Scripts/python.exe"]:
        candidate = venv_path / subpath
        if candidate.exists():
            return str(candidate)
    return None


def has_project_venv(project_root: str | Path) -> bool:
    """True when *project_root* contains a ``venv/`` or ``.venv/``."""
    root = Path(project_root)
    for venv_dir in ("venv", ".venv"):
        if (root / venv_dir / "bin" / "python").exists():
            return True
        if (root / venv_dir / "Scripts" / "python.exe").exists():
            return True
    return False


def resolve_project_python(project_root: str | Path) -> tuple[str, str]:
    """Return ``(python_path, source)`` for *project_root*.

    Same stepped fallback as :meth:`PythonCheckMixin.get_project_python`
    but without warnings, caching, or any other side effects.  ``source``
    is one of the ``PYTHON_SOURCE_*`` constants above.
    """
    root = Path(project_root)

    for venv_dir in ("venv", ".venv"):
        python_path = _find_python_in_venv(root / venv_dir)
        if python_path:
            return python_path, PYTHON_SOURCE_PROJECT_VENV

    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        python_path = _find_python_in_venv(Path(virtual_env))
        if python_path:
            return python_path, PYTHON_SOURCE_VIRTUAL_ENV

    if sys.executable:
        return sys.executable, PYTHON_SOURCE_SYS_EXECUTABLE

    for python_name in ("python3", "python"):
        system_python = shutil.which(python_name)
        if system_python:
            return system_python, PYTHON_SOURCE_PATH

    return "python3", PYTHON_SOURCE_NOT_FOUND


def has_package_json(project_root: str | Path) -> bool:
    return (Path(project_root) / "package.json").exists()


def has_node_modules(project_root: str | Path) -> bool:
    return (Path(project_root) / "node_modules").is_dir()


def is_deno_project(project_root: str | Path) -> bool:
    """Return True when the project uses Deno as its JS/TS runtime.

    Detection: ``deno.json`` or ``deno.jsonc`` at the project root.
    """
    root = Path(project_root)
    return (root / "deno.json").exists() or (root / "deno.jsonc").exists()


def detect_js_package_manager(project_root: str | Path) -> str:
    """Return ``"pnpm"|"yarn"|"npm"`` based on lockfile presence."""
    root = Path(project_root)
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def npmrc_wants_legacy_peer_deps(project_root: str | Path) -> bool:
    """True when ``.npmrc`` sets ``legacy-peer-deps = true``."""
    npmrc_path = Path(project_root) / ".npmrc"
    if not npmrc_path.exists():
        return False
    try:
        for line in npmrc_path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(("#", ";")):
                continue
            key, _, value = stripped.partition("=")
            if key.strip() == "legacy-peer-deps" and value.strip().lower() == "true":
                return True
    except Exception:
        return False
    return False


def suggest_js_install_command(project_root: str | Path) -> str:
    """Return a shell-pastable install line for the detected package manager."""
    pm = detect_js_package_manager(project_root)
    if pm == "pnpm":
        return "pnpm install --no-frozen-lockfile"
    if pm == "yarn":
        return "yarn install --ignore-engines"
    base = "npm install"
    if npmrc_wants_legacy_peer_deps(project_root):
        return f"{base} --legacy-peer-deps"
    return base


_JS_TEST_DIR_NAMES = {"test", "tests", "spec", "__tests__", "e2e", "integration"}
_JS_TEST_FILE_PATTERNS = (
    "*.test.js",
    "*.spec.js",
    "*.test.jsx",
    "*.spec.jsx",
    "*.test.ts",
    "*.spec.ts",
    "*.test.tsx",
    "*.spec.tsx",
)
_JS_TEST_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_JS_SCAN_EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".slopmop",
    ".next",
    ".nuxt",
    ".cache",
    "coverage",
}


class PythonCheckMixin:
    """Mixin for Python-specific check utilities."""

    # Class-level cache for venv warning (only warn once per project_root)
    _venv_warning_shown: set[str] = set()
    # Cache resolved Python path per project_root
    _python_cache: dict[str, str] = {}

    def _find_python_in_venv(self, venv_path: Path) -> Optional[str]:
        """Find Python executable in a venv directory (Unix or Windows)."""
        return _find_python_in_venv(venv_path)

    def _cache_and_return(self, project_root: str, python_path: str) -> str:
        """Cache and return the Python path."""
        PythonCheckMixin._python_cache[project_root] = python_path
        return python_path

    def _get_python_version(self, python_path: str) -> str:
        """Get Python version string, or 'unknown version' on error."""
        try:
            result = subprocess.run(
                [python_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return "unknown version"

    def has_project_venv(self, project_root: str) -> bool:
        """Check if the project has a local discoverable virtual environment.

        Returns True if any of these exist:
        1. project_root/venv/
        2. project_root/.venv/

        An externally activated ``VIRTUAL_ENV`` is a useful fallback runtime, but
        it is not evidence that the repository has its own local dependency
        environment.
        """
        return has_project_venv(project_root)

    @staticmethod
    def suggest_venv_command(project_root: str) -> str:
        """Suggest the right venv creation command for this project.

        Detects the project's package manager and returns an actionable
        command string.  The user can copy-paste it directly.
        """
        root = Path(project_root)

        # Poetry
        if (root / "poetry.lock").exists():
            return "poetry install"
        # Pipenv
        if (root / "Pipfile").exists():
            return "pipenv install --dev"
        # PDM
        if (root / "pdm.lock").exists():
            return "pdm install"
        # Standard: pyproject.toml or requirements.txt
        if (root / "pyproject.toml").exists():
            return "python3 -m venv venv && source venv/bin/activate && pip install -e '.[dev]'"
        if (root / "requirements.txt").exists():
            return "python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
        # Bare minimum
        return "python3 -m venv venv && source venv/bin/activate"

    def check_project_venv_or_warn(
        self, project_root: str, start_time: float
    ) -> Optional[CheckResult]:
        """Return a local warning result when no project venv is found.

        PROJECT-context checks should call this at the top of ``run()``.
        If a venv *does* exist, returns ``None`` so the caller can
        continue with normal execution.

        The warning is intentionally suppressed from SARIF/code-scanning
        output. Missing project dependencies are a local prerequisite
        problem, not a repository code defect.

        Usage::

            result = self.check_project_venv_or_warn(project_root, start_time)
            if result is not None:
                return result
        """
        import time

        if not self.has_project_venv(project_root):
            msg = "No project virtual environment found"
            # Mixin is always composed with BaseCheck
            from slopmop.checks.base import BaseCheck

            return cast(BaseCheck, self)._create_result(
                status=CheckStatus.WARNED,
                duration=time.time() - start_time,
                error=msg,
                fix_suggestion=(
                    "Create a venv so this check can run against your project:\n"
                    f"  cd {project_root} && {self.suggest_venv_command(project_root)}"
                ),
                findings=[Finding(message=msg, level=FindingLevel.WARNING)],
                suppress_sarif=True,
            )
        return None

    def get_project_python(self, project_root: str) -> str:
        """Get the Python executable for the project.

        Uses stepped fallback (project-local venvs prioritized):
        1. ./venv/bin/python or ./.venv/bin/python (project-local - highest priority)
        2. VIRTUAL_ENV environment variable (if no project venv exists)
        3. sys.executable (slop-mop's Python - has all bundled tools)
        4. python3/python in PATH (system Python - last resort)

        Warnings are logged once per project when:
        - Using project venv while VIRTUAL_ENV points to a different venv
        - Falling back to system Python or sys.executable (non-venv)
        """
        if project_root in PythonCheckMixin._python_cache:
            return PythonCheckMixin._python_cache[project_root]

        root = Path(project_root)
        should_warn = project_root not in PythonCheckMixin._venv_warning_shown

        # PRIORITY 1: Check common venv locations in project FIRST
        for venv_dir in ["venv", ".venv"]:
            python_path = self._find_python_in_venv(root / venv_dir)
            if python_path:
                # Warn if VIRTUAL_ENV is set to a different location
                virtual_env = os.environ.get("VIRTUAL_ENV")
                if virtual_env and should_warn:
                    project_venv_path = (root / venv_dir).resolve()
                    virtual_env_path = Path(virtual_env).resolve()
                    if project_venv_path != virtual_env_path:
                        logger.warning(
                            f"⚠️  Using project venv: {project_venv_path}\n"
                            f"   VIRTUAL_ENV is set to: {virtual_env_path}\n"
                            "   This is intentional - project venvs take priority."
                        )
                        PythonCheckMixin._venv_warning_shown.add(project_root)
                return self._cache_and_return(project_root, python_path)

        # PRIORITY 2: Fall back to VIRTUAL_ENV if no project venv exists
        virtual_env = os.environ.get("VIRTUAL_ENV")
        if virtual_env:
            python_path = self._find_python_in_venv(Path(virtual_env))
            if python_path:
                if should_warn:
                    logger.warning(
                        f"⚠️  No project venv found. Using VIRTUAL_ENV: {virtual_env}\n"
                        "   Consider creating ./venv or ./.venv with project dependencies."
                    )
                    PythonCheckMixin._venv_warning_shown.add(project_root)
                return self._cache_and_return(project_root, python_path)
            if should_warn:
                logger.warning(
                    f"VIRTUAL_ENV={virtual_env} set but no Python found there. "
                    "Continuing with fallback detection."
                )

        # No venv found - mark as warned and try sm's own Python
        if should_warn:
            PythonCheckMixin._venv_warning_shown.add(project_root)

        # PRIORITY 3: slop-mop's own Python (has all bundled tools: pip-audit,
        # bandit, detect-secrets, etc.).  Preferred over bare system Python which
        # almost certainly does NOT have these modules installed.
        if sys.executable:
            if should_warn:
                version = self._get_python_version(sys.executable)
                logger.warning(
                    f"⚠️  No virtual environment found in {project_root}. "
                    f"Using slop-mop's Python: {sys.executable} ({version}). "
                    "Security scans will work, but pip-audit will only audit "
                    "packages installed in slop-mop's environment. "
                    "Consider creating a venv with project dependencies."
                )
            return self._cache_and_return(project_root, sys.executable)

        # PRIORITY 4: system Python in PATH (last resort)
        for python_name in ["python3", "python"]:
            system_python = shutil.which(python_name)
            if system_python:
                if should_warn:
                    version = self._get_python_version(system_python)
                    logger.warning(
                        f"⚠️  No Python found for slop-mop. "
                        f"Falling back to system: {system_python} ({version}). "
                        "Security tools (pip-audit, bandit) may not be available."
                    )
                return self._cache_and_return(project_root, system_python)

        # Nothing found at all
        if should_warn:
            logger.warning(
                "⚠️  No Python found anywhere. Security checks will fail. "
                "Create a venv in your project or install Python."
            )
        return self._cache_and_return(project_root, "python3")

    def _python_execution_failed_hint(self) -> str:
        """Return helpful hint text for Python execution failures.

        Use this in fix_suggestion when a Python tool fails to run.
        """
        return (
            "If this is a 'python not found' or 'module not found' error, "
            "ensure your project has a venv/ or .venv/ directory with dependencies "
            "installed. slop-mop will auto-detect and use it."
        )

    def has_python_files(self, project_root: str) -> bool:
        """Check if project has Python files."""
        root = Path(project_root)
        return any(root.rglob("*.py"))

    def has_setup_py(self, project_root: str) -> bool:
        """Check if project has setup.py."""
        return (Path(project_root) / "setup.py").exists()

    def has_pyproject_toml(self, project_root: str) -> bool:
        """Check if project has pyproject.toml."""
        return (Path(project_root) / "pyproject.toml").exists()

    def has_requirements_txt(self, project_root: str) -> bool:
        """Check if project has requirements.txt."""
        return (Path(project_root) / "requirements.txt").exists()

    def is_python_project(self, project_root: str) -> bool:
        """Check if this is a Python project."""
        return (
            self.has_python_files(project_root)
            or self.has_setup_py(project_root)
            or self.has_pyproject_toml(project_root)
            or self.has_requirements_txt(project_root)
        )

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping Python checks."""
        if not self.has_python_files(project_root):
            return "No Python files found"
        if not (
            self.has_setup_py(project_root)
            or self.has_pyproject_toml(project_root)
            or self.has_requirements_txt(project_root)
        ):
            return "No Python project markers (setup.py, pyproject.toml, or requirements.txt)"
        return "Python check not applicable"

    def measure_scope(self, project_root: str) -> Optional[ScopeInfo]:
        """Measure scope for Python checks — counts .py files and LOC.

        Uses include_dirs from config if available, otherwise scans
        the entire project root.
        """
        config = getattr(self, "config", {})
        include_dirs = config.get("include_dirs") or config.get("src_dirs")
        include_list = list(include_dirs) if include_dirs else None
        return count_source_scope(
            project_root, include_dirs=include_list, extensions={".py"}
        )


class JavaScriptCheckMixin:
    """Mixin for JavaScript-specific check utilities."""

    def has_package_json(self, project_root: str) -> bool:
        """Check if project has package.json."""
        return has_package_json(project_root)

    def has_js_files(self, project_root: str) -> bool:
        """Check if project has JavaScript files."""
        root = Path(project_root)
        return any(root.rglob("*.js")) or any(root.rglob("*.ts"))

    def is_javascript_project(self, project_root: str) -> bool:
        """Check if this is a JavaScript project.

        Requires package.json at project root — scattered .js files
        (e.g., vendored tools) don't constitute a JS project we can lint.
        """
        return self.has_package_json(project_root)

    def is_deno_project(self, project_root: str) -> bool:
        """Check if this is a Deno project (deno.json or deno.jsonc)."""
        return is_deno_project(project_root)

    def has_node_modules(self, project_root: str) -> bool:
        """Check if node_modules exists."""
        return has_node_modules(project_root)

    def has_javascript_test_files(
        self,
        project_root: str,
        extra_excludes: set[str] | None = None,
    ) -> bool:
        """Return True when JS/TS test files are present.

        Args:
            project_root: Absolute path to the project.
            extra_excludes: Additional directory paths (relative to
                project_root) to skip during the walk.  Supports both
                simple names (``"vendor"``) and slash-separated paths
                (``"supabase/functions"``).
        """
        root = Path(project_root)
        exclude_dirs = _JS_SCAN_EXCLUDE_DIRS
        if extra_excludes:
            exclude_dirs = exclude_dirs | extra_excludes

        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = Path(dirpath).relative_to(root)
            rel_str = str(rel_dir)

            if set(rel_dir.parts) & exclude_dirs:
                dirnames[:] = []
                continue
            if extra_excludes and rel_str in extra_excludes:
                dirnames[:] = []
                continue

            dirnames[:] = [
                d for d in dirnames if d not in exclude_dirs and not d.startswith(".")
            ]
            is_test_dir = bool(set(rel_dir.parts) & _JS_TEST_DIR_NAMES)

            for filename in filenames:
                suffix = Path(filename).suffix.lower()
                if suffix not in _JS_TEST_EXTS:
                    continue
                if is_test_dir or any(
                    fnmatch(filename, p) for p in _JS_TEST_FILE_PATTERNS
                ):
                    return True
        return False

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping JavaScript checks."""
        if not self.has_package_json(project_root):
            return "No package.json found (not a JavaScript/TypeScript project)"
        if not self.has_js_files(project_root):
            return "No JavaScript/TypeScript files found"
        return "JavaScript check not applicable"

    def _detect_package_manager(self, project_root: str) -> str:
        """Detect which package manager the project uses.

        Resolution order: pnpm-lock.yaml → yarn.lock → package-lock.json → npm
        """
        return detect_js_package_manager(project_root)

    def _get_npm_install_command(self, project_root: str) -> List[str]:
        """Build install command with the correct package manager.

        Detects pnpm/yarn/npm from lockfiles and uses the appropriate
        install command. Falls back to npm if no lockfile found.
        Available to all JavaScript checks via the mixin.
        """
        pm = self._detect_package_manager(project_root)

        if pm == "pnpm":
            return ["pnpm", "install", "--no-frozen-lockfile"]
        if pm == "yarn":
            return ["yarn", "install", "--ignore-engines"]

        # npm path
        cmd = ["npm", "install"]

        # Add flags from config (handle string or list)
        # Uses self.config from BaseCheck
        config_flags = getattr(self, "config", {}).get("npm_install_flags", [])
        if isinstance(config_flags, str):
            config_flags = [config_flags]
        cmd.extend(config_flags)

        if (
            npmrc_wants_legacy_peer_deps(project_root)
            and "--legacy-peer-deps" not in cmd
        ):
            cmd.append("--legacy-peer-deps")

        return cmd

    def measure_scope(self, project_root: str) -> Optional[ScopeInfo]:
        """Measure scope for JavaScript checks — counts JS/TS files and LOC.

        Uses include_dirs from config if available, otherwise scans
        the entire project root.
        """
        config = getattr(self, "config", {})
        include_dirs = config.get("include_dirs") or config.get("src_dirs")
        include_list = list(include_dirs) if include_dirs else None
        return count_source_scope(
            project_root,
            include_dirs=include_list,
            extensions={".js", ".ts", ".jsx", ".tsx"},
        )
