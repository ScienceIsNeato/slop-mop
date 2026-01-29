"""Tests for base check module."""

from unittest.mock import MagicMock

from slopbucket.checks.base import (
    BaseCheck,
    GateCategory,
    JavaScriptCheckMixin,
    PythonCheckMixin,
)
from slopbucket.core.result import CheckResult, CheckStatus


class ConcreteCheck(BaseCheck):
    """Concrete implementation of BaseCheck for testing."""

    @property
    def name(self) -> str:
        return "test-check"

    @property
    def display_name(self) -> str:
        return "Test Check"

    @property
    def category(self) -> GateCategory:
        return GateCategory.PYTHON

    def is_applicable(self, project_root: str) -> bool:
        return True

    def run(self, project_root: str) -> CheckResult:
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASSED,
            duration=0.1,
        )


class TestBaseCheck:
    """Tests for BaseCheck abstract class."""

    def test_init_with_config(self):
        """Test initialization with config."""
        config = {"key": "value"}
        check = ConcreteCheck(config)
        assert check.config == config

    def test_init_with_runner(self):
        """Test initialization with custom runner."""
        mock_runner = MagicMock()
        check = ConcreteCheck({}, runner=mock_runner)
        assert check._runner is mock_runner

    def test_depends_on_default(self):
        """Test default depends_on is empty list."""
        check = ConcreteCheck({})
        assert check.depends_on == []

    def test_can_auto_fix_default(self):
        """Test default can_auto_fix returns False."""
        check = ConcreteCheck({})
        assert check.can_auto_fix() is False

    def test_auto_fix_default(self):
        """Test default auto_fix returns False."""
        check = ConcreteCheck({})
        assert check.auto_fix("/tmp") is False

    def test_create_result(self):
        """Test _create_result helper."""
        check = ConcreteCheck({})
        result = check._create_result(
            status=CheckStatus.PASSED,
            duration=1.5,
            output="Test output",
        )

        # Result name is the full_name (category:name)
        assert result.name == "python:test-check"
        assert result.status == CheckStatus.PASSED
        assert result.duration == 1.5
        assert result.output == "Test output"

    def test_create_result_with_error(self):
        """Test _create_result with error."""
        check = ConcreteCheck({})
        result = check._create_result(
            status=CheckStatus.FAILED,
            duration=1.0,
            error="Something went wrong",
            fix_suggestion="Fix it",
        )

        assert result.status == CheckStatus.FAILED
        assert result.error == "Something went wrong"
        assert result.fix_suggestion == "Fix it"

    def test_run_command(self):
        """Test _run_command helper."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = MagicMock(returncode=0)
        check = ConcreteCheck({}, runner=mock_runner)

        check._run_command(["echo", "test"], cwd="/tmp")

        mock_runner.run.assert_called_once_with(
            ["echo", "test"],
            cwd="/tmp",
            timeout=None,
        )


class TestPythonCheckMixin:
    """Tests for PythonCheckMixin."""

    def setup_method(self):
        """Create a mixin instance for testing."""

        class TestMixin(PythonCheckMixin):
            pass

        self.mixin = TestMixin()

    def test_has_python_files_true(self, tmp_path):
        """Test has_python_files returns True when Python files exist."""
        (tmp_path / "test.py").touch()
        assert self.mixin.has_python_files(str(tmp_path)) is True

    def test_has_python_files_false(self, tmp_path):
        """Test has_python_files returns False when no Python files."""
        (tmp_path / "test.txt").touch()
        assert self.mixin.has_python_files(str(tmp_path)) is False

    def test_has_python_files_nested(self, tmp_path):
        """Test has_python_files finds nested Python files."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "test.py").touch()
        assert self.mixin.has_python_files(str(tmp_path)) is True

    def test_has_setup_py_true(self, tmp_path):
        """Test has_setup_py returns True when setup.py exists."""
        (tmp_path / "setup.py").touch()
        assert self.mixin.has_setup_py(str(tmp_path)) is True

    def test_has_setup_py_false(self, tmp_path):
        """Test has_setup_py returns False when setup.py doesn't exist."""
        assert self.mixin.has_setup_py(str(tmp_path)) is False

    def test_has_pyproject_toml_true(self, tmp_path):
        """Test has_pyproject_toml returns True when pyproject.toml exists."""
        (tmp_path / "pyproject.toml").touch()
        assert self.mixin.has_pyproject_toml(str(tmp_path)) is True

    def test_has_pyproject_toml_false(self, tmp_path):
        """Test has_pyproject_toml returns False when pyproject.toml doesn't exist."""
        assert self.mixin.has_pyproject_toml(str(tmp_path)) is False

    def test_has_requirements_txt_true(self, tmp_path):
        """Test has_requirements_txt returns True when requirements.txt exists."""
        (tmp_path / "requirements.txt").touch()
        assert self.mixin.has_requirements_txt(str(tmp_path)) is True

    def test_has_requirements_txt_false(self, tmp_path):
        """Test has_requirements_txt returns False when requirements.txt doesn't exist."""
        assert self.mixin.has_requirements_txt(str(tmp_path)) is False

    def test_is_python_project_with_setup_py(self, tmp_path):
        """Test is_python_project returns True with setup.py."""
        (tmp_path / "setup.py").touch()
        assert self.mixin.is_python_project(str(tmp_path)) is True

    def test_is_python_project_with_pyproject(self, tmp_path):
        """Test is_python_project returns True with pyproject.toml."""
        (tmp_path / "pyproject.toml").touch()
        assert self.mixin.is_python_project(str(tmp_path)) is True

    def test_is_python_project_with_requirements(self, tmp_path):
        """Test is_python_project returns True with requirements.txt."""
        (tmp_path / "requirements.txt").touch()
        assert self.mixin.is_python_project(str(tmp_path)) is True

    def test_is_python_project_with_py_files(self, tmp_path):
        """Test is_python_project returns True with .py files."""
        (tmp_path / "main.py").touch()
        assert self.mixin.is_python_project(str(tmp_path)) is True

    def test_is_python_project_false(self, tmp_path):
        """Test is_python_project returns False for non-Python project."""
        (tmp_path / "index.js").touch()
        assert self.mixin.is_python_project(str(tmp_path)) is False


class TestJavaScriptCheckMixin:
    """Tests for JavaScriptCheckMixin."""

    def setup_method(self):
        """Create a mixin instance for testing."""

        class TestMixin(JavaScriptCheckMixin):
            pass

        self.mixin = TestMixin()

    def test_has_package_json_true(self, tmp_path):
        """Test has_package_json returns True when package.json exists."""
        (tmp_path / "package.json").touch()
        assert self.mixin.has_package_json(str(tmp_path)) is True

    def test_has_package_json_false(self, tmp_path):
        """Test has_package_json returns False when package.json doesn't exist."""
        assert self.mixin.has_package_json(str(tmp_path)) is False

    def test_has_js_files_true(self, tmp_path):
        """Test has_js_files returns True when JS files exist."""
        (tmp_path / "app.js").touch()
        assert self.mixin.has_js_files(str(tmp_path)) is True

    def test_has_js_files_ts(self, tmp_path):
        """Test has_js_files returns True for TypeScript files."""
        (tmp_path / "app.ts").touch()
        assert self.mixin.has_js_files(str(tmp_path)) is True

    def test_has_js_files_false(self, tmp_path):
        """Test has_js_files returns False when no JS files."""
        (tmp_path / "app.py").touch()
        assert self.mixin.has_js_files(str(tmp_path)) is False

    def test_is_javascript_project_with_package_json(self, tmp_path):
        """Test is_javascript_project returns True with package.json."""
        (tmp_path / "package.json").touch()
        assert self.mixin.is_javascript_project(str(tmp_path)) is True

    def test_is_javascript_project_with_js_files(self, tmp_path):
        """Test is_javascript_project returns True with JS files."""
        (tmp_path / "index.js").touch()
        assert self.mixin.is_javascript_project(str(tmp_path)) is True

    def test_is_javascript_project_false(self, tmp_path):
        """Test is_javascript_project returns False for non-JS project."""
        (tmp_path / "main.py").touch()
        assert self.mixin.is_javascript_project(str(tmp_path)) is False

    def test_has_node_modules_true(self, tmp_path):
        """Test has_node_modules returns True when node_modules exists."""
        (tmp_path / "node_modules").mkdir()
        assert self.mixin.has_node_modules(str(tmp_path)) is True

    def test_has_node_modules_false(self, tmp_path):
        """Test has_node_modules returns False when node_modules doesn't exist."""
        assert self.mixin.has_node_modules(str(tmp_path)) is False
