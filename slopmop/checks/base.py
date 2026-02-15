"""Abstract base class for quality gate checks.

All quality checks inherit from BaseCheck and implement the required methods.
This enables the Open/Closed principle - add new checks without modifying
existing code.
"""

import logging
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from slopmop.core.result import CheckResult, CheckStatus
from slopmop.subprocess.runner import SubprocessResult, SubprocessRunner, get_runner

logger = logging.getLogger(__name__)


def find_tool(name: str, project_root: str) -> Optional[str]:
    """Find a tool executable, checking the project venv first.

    VS Code git hooks and other non-interactive contexts don't activate
    the venv, so tools installed there (vulture, pyright, etc.) aren't
    on $PATH. This checks venv/bin/<name> before falling back to
    shutil.which().

    Args:
        name: Executable name (e.g. "vulture", "pyright").
        project_root: Project root directory.

    Returns:
        Absolute path to the executable, or None if not found.
    """
    root = Path(project_root)
    for venv_dir in ["venv", ".venv"]:
        candidate = root / venv_dir / "bin" / name
        if candidate.exists():
            return str(candidate)
        # Windows
        candidate = root / venv_dir / "Scripts" / f"{name}.exe"
        if candidate.exists():
            return str(candidate)

    return shutil.which(name)


class GateCategory(Enum):
    """Categories for organizing quality gates by language/type."""

    PYTHON = ("python", "🐍", "Python")
    JAVASCRIPT = ("javascript", "📦", "JavaScript")
    SECURITY = ("security", "🔐", "Security")
    QUALITY = ("quality", "📊", "Quality")
    GENERAL = ("general", "🔧", "General")
    INTEGRATION = ("integration", "🎭", "Integration")
    PR = ("pr", "🔀", "Pull Request")

    def __init__(self, key: str, emoji: str, display_name: str):
        self.key = key
        self.emoji = emoji
        self._display_name = display_name

    @property
    def display(self) -> str:
        return f"{self.emoji} {self._display_name}"

    @property
    def display_name(self) -> str:
        """Human-readable category name."""
        return self._display_name


@dataclass
class ConfigField:
    """Definition of a configuration field for a check."""

    name: str
    field_type: str  # "boolean", "integer", "string", "string[]"
    default: Any
    description: str = ""
    required: bool = False
    min_value: Optional[int] = None  # For integers
    max_value: Optional[int] = None  # For integers
    choices: Optional[List[str]] = None  # For enums


# Standard config fields that all gates have
STANDARD_CONFIG_FIELDS = [
    ConfigField(
        name="enabled",
        field_type="boolean",
        default=False,
        description="Whether this gate is enabled",
    ),
    ConfigField(
        name="auto_fix",
        field_type="boolean",
        default=False,
        description="Automatically fix issues when possible",
    ),
    ConfigField(
        name="config_file_path",
        field_type="string",
        default=None,
        description="Path to tool's native config file (e.g., pytest.ini, .bandit)",
        required=False,
    ),
]


class BaseCheck(ABC):
    """Abstract base class for all quality gate checks.

    Subclasses must implement:
    - name: Unique identifier for the check (e.g., 'lint-format')
    - display_name: Human-readable name with emoji
    - category: GateCategory for this check
    - is_applicable(): Whether check applies to current project
    - run(): Execute the check and return result

    Optional overrides:
    - depends_on: List of check names this depends on
    - config_schema: Additional config fields beyond standard ones
    - can_auto_fix(): Whether issues can be auto-fixed
    - auto_fix(): Attempt to fix issues automatically
    """

    def __init__(
        self, config: Dict[str, Any], runner: Optional[SubprocessRunner] = None
    ):
        """Initialize the check.

        Args:
            config: Configuration dictionary for this check
            runner: Subprocess runner to use (default: global runner)
        """
        self.config = config
        self._runner = runner or get_runner()

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this check.

        This should be a lowercase, hyphenated string like 'lint-format'.
        Note: Do NOT include the language prefix - that comes from category.
        """

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable display name with emoji.

        Example: '🎨 Lint & Format (black, isort, flake8)'
        """

    @property
    @abstractmethod
    def category(self) -> GateCategory:
        """The language/type category for this check.

        Returns:
            GateCategory enum value (PYTHON, JAVASCRIPT, GENERAL, INTEGRATION)
        """

    @property
    def full_name(self) -> str:
        """Full name including category prefix.

        Returns:
            String like 'python:lint-format'
        """
        return f"{self.category.key}:{self.name}"

    @property
    def depends_on(self) -> List[str]:
        """List of check names this check depends on.

        Override to specify dependencies. Dependent checks run after their
        dependencies complete successfully.
        """
        return []

    @property
    def superseded_by(self) -> Optional[str]:
        """Full name of check that supersedes this one.

        If another check fully encompasses this check's functionality,
        return its full name (e.g., 'security:full'). This prevents
        recommending a subset check when its superset is already running.

        Returns:
            Full name of superseding check, or None if not superseded
        """
        return None

    @property
    def config_schema(self) -> List[ConfigField]:
        """Additional configuration fields for this check.

        Override to add check-specific config fields beyond the standard ones
        (enabled, auto_fix). Standard fields are automatically included.

        Returns:
            List of ConfigField definitions
        """
        return []

    def get_full_config_schema(self) -> List[ConfigField]:
        """Get complete config schema including standard fields.

        Returns:
            List of all ConfigField definitions (standard + check-specific)
        """
        return STANDARD_CONFIG_FIELDS + self.config_schema

    @abstractmethod
    def is_applicable(self, project_root: str) -> bool:
        """Return True if this check applies to the given project.

        Args:
            project_root: Path to project root directory

        Returns:
            True if check should run, False to skip
        """

    def skip_reason(self, project_root: str) -> str:
        """Return reason why this check is not applicable.

        Called when is_applicable returns False to provide a human-readable
        explanation for why the check was skipped.

        Default implementation provides a generic message based on check type.
        Override for more specific skip reasons.

        Args:
            project_root: Path to project root directory

        Returns:
            Human-readable skip reason
        """
        # Default implementation tries to provide helpful context
        category = self.category.display_name if self.category else "Unknown"
        return f"No {category} code detected in project"

    @abstractmethod
    def run(self, project_root: str) -> CheckResult:
        """Execute the check and return result.

        Args:
            project_root: Path to project root directory

        Returns:
            CheckResult with status, output, and any error info
        """

    def can_auto_fix(self) -> bool:
        """Return True if this check can automatically fix issues.

        Override to enable auto-fix capability.
        """
        return False

    def auto_fix(self, project_root: str) -> bool:
        """Attempt to automatically fix issues.

        Args:
            project_root: Path to project root directory

        Returns:
            True if fix was successful, False otherwise
        """
        return False

    def _create_result(
        self,
        status: CheckStatus,
        duration: float,
        output: str = "",
        error: Optional[str] = None,
        fix_suggestion: Optional[str] = None,
        auto_fixed: bool = False,
    ) -> CheckResult:
        """Helper to create a CheckResult for this check.

        Args:
            status: Check status
            duration: Execution time in seconds
            output: Check output
            error: Error message if failed
            fix_suggestion: Suggested fix for failures
            auto_fixed: Whether issues were auto-fixed

        Returns:
            CheckResult instance
        """
        return CheckResult(
            name=self.full_name,
            status=status,
            duration=duration,
            output=output,
            error=error,
            fix_suggestion=fix_suggestion,
            auto_fixed=auto_fixed,
        )

    def _run_command(
        self,
        command: List[str],
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> SubprocessResult:
        """Run a command using the subprocess runner.

        Args:
            command: Command to run
            cwd: Working directory
            timeout: Timeout in seconds

        Returns:
            SubprocessResult
        """
        return self._runner.run(command, cwd=cwd, timeout=timeout)


class PythonCheckMixin:
    """Mixin for Python-specific check utilities."""

    # Class-level cache for venv warning (only warn once per project_root)
    _venv_warning_shown: set[str] = set()
    # Cache resolved Python path per project_root
    _python_cache: dict[str, str] = {}

    def _find_python_in_venv(self, venv_path: Path) -> Optional[str]:
        """Find Python executable in a venv directory (Unix or Windows)."""
        for subpath in ["bin/python", "Scripts/python.exe"]:
            python_path = venv_path / subpath
            if python_path.exists():
                return str(python_path)
        return None

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

    def get_project_python(self, project_root: str) -> str:
        """Get the Python executable for the project.

        Uses stepped fallback (project-local venvs prioritized):
        1. ./venv/bin/python or ./.venv/bin/python (project-local - highest priority)
        2. VIRTUAL_ENV environment variable (if no project venv exists)
        3. python3/python in PATH (system Python)
        4. sys.executable (slop-mop's Python - last resort)

        Warnings are logged once per project when:
        - Using project venv while VIRTUAL_ENV points to a different venv
        - Falling back to system Python or sys.executable (non-venv)
        """
        if project_root in PythonCheckMixin._python_cache:
            return PythonCheckMixin._python_cache[project_root]

        import os
        import shutil
        import sys

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

        # No venv found - mark as warned and try system Python
        if should_warn:
            PythonCheckMixin._venv_warning_shown.add(project_root)

        # Try to find python3 or python in PATH
        for python_name in ["python3", "python"]:
            system_python = shutil.which(python_name)
            if system_python:
                if should_warn:
                    version = self._get_python_version(system_python)
                    logger.warning(
                        f"⚠️  No virtual environment found in {project_root}. "
                        f"Using system Python: {system_python} ({version}). "
                        "Consider creating a venv with project dependencies."
                    )
                return self._cache_and_return(project_root, system_python)

        # Ultimate fallback: slop-mop's own Python
        if should_warn:
            logger.warning(
                f"⚠️  No Python found in PATH. Using slop-mop's Python: {sys.executable}. "
                "This will likely fail if the project has dependencies not installed "
                "in slop-mop's environment. Create a venv in your project!"
            )
        return self._cache_and_return(project_root, sys.executable)

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


class JavaScriptCheckMixin:
    """Mixin for JavaScript-specific check utilities."""

    def has_package_json(self, project_root: str) -> bool:
        """Check if project has package.json."""
        return (Path(project_root) / "package.json").exists()

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

    def has_node_modules(self, project_root: str) -> bool:
        """Check if node_modules exists."""
        return (Path(project_root) / "node_modules").is_dir()

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping JavaScript checks."""
        if not self.has_package_json(project_root):
            return "No package.json found (not a JavaScript/TypeScript project)"
        if not self.has_js_files(project_root):
            return "No JavaScript/TypeScript files found"
        return "JavaScript check not applicable"

    def _get_npm_install_command(self, project_root: str) -> List[str]:
        """Build npm install command with appropriate flags.

        Checks both config (npm_install_flags) and .npmrc (legacy-peer-deps).
        Available to all JavaScript checks via the mixin.
        """
        cmd = ["npm", "install"]

        # Add flags from config (handle string or list)
        # Uses self.config from BaseCheck
        config_flags = getattr(self, "config", {}).get("npm_install_flags", [])
        if isinstance(config_flags, str):
            config_flags = [config_flags]
        cmd.extend(config_flags)

        # Check .npmrc for legacy-peer-deps
        npmrc_path = Path(project_root) / ".npmrc"
        if npmrc_path.exists():
            try:
                content = npmrc_path.read_text()
                # Parse line by line, ignoring comments (# and ;)
                for line in content.splitlines():
                    line = line.strip()
                    # Skip comment lines
                    if line.startswith("#") or line.startswith(";"):
                        continue
                    # Check for active legacy-peer-deps setting
                    if (
                        "legacy-peer-deps=true" in line
                        and "--legacy-peer-deps" not in cmd
                    ):
                        cmd.append("--legacy-peer-deps")
                        break
            except Exception:
                pass  # Ignore .npmrc read errors

        return cmd
