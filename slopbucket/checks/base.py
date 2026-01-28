"""Abstract base class for quality gate checks.

All quality checks inherit from BaseCheck and implement the required methods.
This enables the Open/Closed principle - add new checks without modifying
existing code.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from slopbucket.core.result import CheckResult, CheckStatus
from slopbucket.subprocess.runner import SubprocessRunner, get_runner


class BaseCheck(ABC):
    """Abstract base class for all quality gate checks.

    Subclasses must implement:
    - name: Unique identifier for the check
    - display_name: Human-readable name with emoji
    - is_applicable(): Whether check applies to current project
    - run(): Execute the check and return result

    Optional overrides:
    - depends_on: List of check names this depends on
    - can_auto_fix(): Whether issues can be auto-fixed
    - auto_fix(): Attempt to fix issues automatically
    """

    def __init__(self, config: Dict, runner: Optional[SubprocessRunner] = None):
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

        This should be a lowercase, hyphenated string like 'python-lint-format'.
        """
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable display name with emoji.

        Example: '🎨 Python Lint & Format (black, isort, flake8)'
        """
        pass

    @property
    def depends_on(self) -> List[str]:
        """List of check names this check depends on.

        Override to specify dependencies. Dependent checks run after their
        dependencies complete successfully.
        """
        return []

    @abstractmethod
    def is_applicable(self, project_root: str) -> bool:
        """Return True if this check applies to the given project.

        Args:
            project_root: Path to project root directory

        Returns:
            True if check should run, False to skip
        """
        pass

    @abstractmethod
    def run(self, project_root: str) -> CheckResult:
        """Execute the check and return result.

        Args:
            project_root: Path to project root directory

        Returns:
            CheckResult with status, output, and any error info
        """
        pass

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
            name=self.name,
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
    ):
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
        """Check if this is a JavaScript project."""
        return self.has_package_json(project_root) or self.has_js_files(project_root)

    def has_node_modules(self, project_root: str) -> bool:
        """Check if node_modules exists."""
        return (Path(project_root) / "node_modules").is_dir()
