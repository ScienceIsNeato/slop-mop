"""Tests for base check module."""

from unittest.mock import MagicMock

from slopmop.checks.base import (
    BaseCheck,
    Flaw,
    GateCategory,
    JavaScriptCheckMixin,
    PythonCheckMixin,
)
from slopmop.core.result import CheckResult, CheckStatus


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
        return GateCategory.OVERCONFIDENCE

    @property
    def flaw(self) -> Flaw:
        return Flaw.OVERCONFIDENCE

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

    def test_auto_fix_default(self, tmp_path):
        """Test default auto_fix returns False."""
        check = ConcreteCheck({})
        assert check.auto_fix(str(tmp_path)) is False

    def test_create_result(self):
        """Test _create_result helper."""
        check = ConcreteCheck({})
        result = check._create_result(
            status=CheckStatus.PASSED,
            duration=1.5,
            output="Test output",
        )

        # Result name is the full_name (category:name)
        assert result.name == "overconfidence:test-check"
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

    def test_run_command(self, tmp_path):
        """Test _run_command helper."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = MagicMock(returncode=0)
        check = ConcreteCheck({}, runner=mock_runner)

        check._run_command(["echo", "test"], cwd=str(tmp_path))

        mock_runner.run.assert_called_once_with(
            ["echo", "test"],
            cwd=str(tmp_path),
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

    def test_skip_reason_no_python_files(self, tmp_path):
        """Test skip_reason returns correct message when no Python files."""
        (tmp_path / "index.js").touch()
        reason = self.mixin.skip_reason(str(tmp_path))
        assert "No Python files" in reason

    def test_skip_reason_with_python_files(self, tmp_path):
        """Test skip_reason returns generic message when Python files exist."""
        (tmp_path / "main.py").touch()
        (tmp_path / "pyproject.toml").touch()
        reason = self.mixin.skip_reason(str(tmp_path))
        assert "not applicable" in reason.lower()

    def test_get_project_python_uses_venv(self, tmp_path, monkeypatch):
        """Test get_project_python prefers ./venv/bin/python."""
        venv_dir = tmp_path / "venv" / "bin"
        venv_dir.mkdir(parents=True)
        python_path = venv_dir / "python"
        python_path.touch()
        python_path.chmod(0o755)

        # Clear VIRTUAL_ENV to ensure it doesn't interfere
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)

        result = self.mixin.get_project_python(str(tmp_path))
        assert result == str(python_path)

    def test_get_project_python_uses_dot_venv(self, tmp_path, monkeypatch):
        """Test get_project_python prefers ./.venv/bin/python when ./venv doesn't exist."""
        venv_dir = tmp_path / ".venv" / "bin"
        venv_dir.mkdir(parents=True)
        python_path = venv_dir / "python"
        python_path.touch()
        python_path.chmod(0o755)

        # Clear VIRTUAL_ENV to ensure it doesn't interfere
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)

        result = self.mixin.get_project_python(str(tmp_path))
        assert result == str(python_path)

    def test_get_project_python_prefers_virtual_env_var(self, tmp_path, monkeypatch):
        """Test get_project_python prefers project venv over VIRTUAL_ENV."""
        # Create venv from env var
        env_venv = tmp_path / "env_venv" / "bin"
        env_venv.mkdir(parents=True)
        env_python = env_venv / "python"
        env_python.touch()
        env_python.chmod(0o755)

        # Also create project venv (should be preferred)
        project_venv = tmp_path / "venv" / "bin"
        project_venv.mkdir(parents=True)
        project_python = project_venv / "python"
        project_python.touch()
        project_python.chmod(0o755)

        monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "env_venv"))

        result = self.mixin.get_project_python(str(tmp_path))
        assert result == str(project_python)

    def test_get_project_python_falls_back_to_system_python(
        self, tmp_path, monkeypatch
    ):
        """Test get_project_python falls back to system Python when no venv."""
        import shutil

        # Clear VIRTUAL_ENV
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)

        result = self.mixin.get_project_python(str(tmp_path))

        # Should find python3 or python in PATH (system Python)
        expected = shutil.which("python3") or shutil.which("python")
        if expected:
            assert result == expected
        else:
            # If no system Python, falls back to sys.executable
            import sys

            assert result == sys.executable

    def test_get_project_python_falls_back_to_sys_executable_no_path(
        self, tmp_path, monkeypatch
    ):
        """Test get_project_python falls back to sys.executable if no Python in PATH."""
        import sys

        # Clear VIRTUAL_ENV
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)

        # Mock shutil.which to return None (no Python in PATH)
        monkeypatch.setattr("shutil.which", lambda x: None)

        result = self.mixin.get_project_python(str(tmp_path))
        assert result == sys.executable

    def test_get_project_python_logs_warning_no_venv(
        self, tmp_path, monkeypatch, caplog
    ):
        """Test get_project_python logs warning when no venv found."""
        import logging

        # Clear VIRTUAL_ENV
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)

        with caplog.at_level(logging.WARNING):
            self.mixin.get_project_python(str(tmp_path))

        # Should have logged a warning about no venv
        assert any("No virtual environment found" in msg for msg in caplog.messages)

    def test_python_execution_failed_hint(self):
        """Test _python_execution_failed_hint returns helpful text."""
        hint = self.mixin._python_execution_failed_hint()
        assert "venv" in hint
        assert "module not found" in hint

    def test_get_project_python_venv_takes_priority_over_dot_venv(
        self, tmp_path, monkeypatch
    ):
        """Test get_project_python prefers ./venv over ./.venv."""
        # Create both venvs
        venv_dir = tmp_path / "venv" / "bin"
        venv_dir.mkdir(parents=True)
        venv_python = venv_dir / "python"
        venv_python.touch()
        venv_python.chmod(0o755)

        dot_venv_dir = tmp_path / ".venv" / "bin"
        dot_venv_dir.mkdir(parents=True)
        (dot_venv_dir / "python").touch()

        monkeypatch.delenv("VIRTUAL_ENV", raising=False)

        result = self.mixin.get_project_python(str(tmp_path))
        assert result == str(venv_python)


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
        """Test is_javascript_project returns False with only JS files (no package.json)."""
        (tmp_path / "index.js").touch()
        assert self.mixin.is_javascript_project(str(tmp_path)) is False

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

    def test_skip_reason_no_package_json(self, tmp_path):
        """Test skip_reason returns correct message when no package.json."""
        (tmp_path / "app.py").touch()
        reason = self.mixin.skip_reason(str(tmp_path))
        assert "No package.json" in reason

    def test_skip_reason_with_package_json_no_js_files(self, tmp_path):
        """Test skip_reason when package.json exists but no JS files."""
        (tmp_path / "package.json").touch()
        # When package.json exists, is_javascript_project returns True
        # So skip_reason should give a generic message
        # But our implementation checks for JS files absence
        reason = self.mixin.skip_reason(str(tmp_path))
        # With package.json but no JS files, it returns the JS files message
        assert "JavaScript" in reason or "not applicable" in reason.lower()
