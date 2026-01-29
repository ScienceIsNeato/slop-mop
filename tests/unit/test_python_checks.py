"""Tests for Python check implementations."""

from unittest.mock import MagicMock

from slopbucket.checks.python.coverage import PythonCoverageCheck
from slopbucket.checks.python.lint_format import PythonLintFormatCheck
from slopbucket.checks.python.static_analysis import PythonStaticAnalysisCheck
from slopbucket.checks.python.tests import PythonTestsCheck
from slopbucket.core.result import CheckStatus
from slopbucket.subprocess.runner import SubprocessResult


class TestPythonLintFormatCheck:
    """Tests for PythonLintFormatCheck."""

    def test_name(self):
        """Test check name."""
        check = PythonLintFormatCheck({})
        assert check.name == "lint-format"

    def test_display_name(self):
        """Test check display name."""
        check = PythonLintFormatCheck({})
        assert "Lint" in check.display_name
        assert "Format" in check.display_name
        assert "black" in check.display_name

    def test_is_applicable_python_project(self, tmp_path):
        """Test is_applicable returns True for Python project."""
        (tmp_path / "setup.py").touch()
        check = PythonLintFormatCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_non_python(self, tmp_path):
        """Test is_applicable returns False for non-Python project."""
        (tmp_path / "package.json").touch()
        check = PythonLintFormatCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_can_auto_fix(self):
        """Test can_auto_fix returns True."""
        check = PythonLintFormatCheck({})
        assert check.can_auto_fix() is True

    def test_auto_fix_success(self, tmp_path):
        """Test auto_fix runs black and isort."""
        (tmp_path / "slopbucket").mkdir()
        (tmp_path / "slopbucket" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="", stderr="", duration=1.0
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check.auto_fix(str(tmp_path))

        assert result is True
        # Should have called black and isort
        assert mock_runner.run.call_count >= 2

    def test_run_success(self, tmp_path):
        """Test run with passing checks."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        mock_runner = MagicMock()
        # All checks pass
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="", stderr="", duration=1.0
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_black_fails(self, tmp_path):
        """Test run when black fails."""
        (tmp_path / "test.py").touch()

        mock_runner = MagicMock()
        # Black fails on format check
        mock_runner.run.return_value = SubprocessResult(
            returncode=1, stdout="would reformat test.py", stderr="", duration=1.0
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_get_python_targets_excludes_special_dirs(self, tmp_path):
        """Test _get_python_targets excludes venv, .git, etc."""
        # Create excluded directories
        (tmp_path / "venv").mkdir()
        (tmp_path / "venv" / "__init__.py").touch()
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden" / "__init__.py").touch()
        (tmp_path / "node_modules").mkdir()

        # Create valid target
        (tmp_path / "mypackage").mkdir()
        (tmp_path / "mypackage" / "__init__.py").touch()

        check = PythonLintFormatCheck({})
        targets = check._get_python_targets(str(tmp_path))

        assert "mypackage" in targets
        assert "venv" not in targets
        assert ".hidden" not in targets
        assert "node_modules" not in targets

    def test_get_python_targets_includes_standard_dirs(self, tmp_path):
        """Test _get_python_targets includes src, tests, lib dirs."""
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()

        check = PythonLintFormatCheck({})
        targets = check._get_python_targets(str(tmp_path))

        assert "src" in targets
        assert "tests" in targets

    def test_auto_fix_falls_back_to_current_dir(self, tmp_path):
        """Test auto_fix uses '.' when no targets found."""
        # Empty directory
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="", stderr="", duration=1.0
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check.auto_fix(str(tmp_path))

        assert result is True

    def test_check_black_no_targets(self, tmp_path):
        """Test _check_black returns None when no targets."""
        # Empty directory
        check = PythonLintFormatCheck({})
        result = check._check_black(str(tmp_path))

        assert result is None

    def test_check_black_fails_no_specific_files(self, tmp_path):
        """Test _check_black when black fails but no specific files listed."""
        (tmp_path / "test.py").touch()

        mock_runner = MagicMock()
        # Black fails but no "would reformat" lines
        mock_runner.run.return_value = SubprocessResult(
            returncode=1, stdout="oh no an error occurred", stderr="", duration=1.0
        )

        check = PythonLintFormatCheck({}, runner=mock_runner)
        result = check._check_black(str(tmp_path))

        assert result == "Formatting check failed"


class TestPythonTestsCheck:
    """Tests for PythonTestsCheck."""

    def test_name(self):
        """Test check name."""
        check = PythonTestsCheck({})
        assert check.name == "tests"

    def test_display_name(self):
        """Test check display name."""
        check = PythonTestsCheck({})
        assert "Tests" in check.display_name or "test" in check.display_name.lower()

    def test_is_applicable_python_project(self, tmp_path):
        """Test is_applicable returns True for Python project."""
        (tmp_path / "pyproject.toml").touch()
        check = PythonTestsCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_depends_on(self):
        """Test check dependencies."""
        check = PythonTestsCheck({})
        # Tests depend on lint-format being run first
        assert "python:lint-format" in check.depends_on

    def test_run_success(self, tmp_path):
        """Test run with passing tests."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="10 passed in 0.5s", stderr="", duration=1.0
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_tests_fail(self, tmp_path):
        """Test run when tests fail."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="FAILED tests/test_foo.py::test_bar - AssertionError",
            stderr="",
            duration=1.0,
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_run_coverage_fail_only(self, tmp_path):
        """Test run passes when only coverage fails (not tests)."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="10 passed\nFail Required test coverage of 80%",
            stderr="",
            duration=1.0,
        )

        check = PythonTestsCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        # Should pass because tests passed, only coverage failed
        assert result.status == CheckStatus.PASSED


class TestPythonCoverageCheck:
    """Tests for PythonCoverageCheck."""

    def test_name(self):
        """Test check name."""
        check = PythonCoverageCheck({})
        assert check.name == "coverage"

    def test_display_name(self):
        """Test check display name."""
        check = PythonCoverageCheck({})
        assert "Coverage" in check.display_name

    def test_depends_on(self):
        """Test check dependencies."""
        check = PythonCoverageCheck({})
        assert "python:tests" in check.depends_on

    def test_is_applicable_python_project(self, tmp_path):
        """Test is_applicable returns True for Python project."""
        (tmp_path / "requirements.txt").touch()
        check = PythonCoverageCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_run_coverage_above_threshold(self, tmp_path):
        """Test run when coverage is above threshold."""
        # Create coverage.xml file
        (tmp_path / "coverage.xml").write_text("<coverage></coverage>")

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="TOTAL    1000    100    90%", stderr="", duration=1.0
        )

        check = PythonCoverageCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_coverage_below_threshold(self, tmp_path):
        """Test run when coverage is below threshold."""
        # Create coverage.xml file
        (tmp_path / "coverage.xml").write_text("<coverage></coverage>")

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="TOTAL    1000    500    50%", stderr="", duration=1.0
        )

        check = PythonCoverageCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_run_no_coverage_data(self, tmp_path):
        """Test run when no coverage data exists."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1, stdout="No data to report", stderr="", duration=1.0
        )

        check = PythonCoverageCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED


class TestPythonStaticAnalysisCheck:
    """Tests for PythonStaticAnalysisCheck."""

    def test_name(self):
        """Test check name."""
        check = PythonStaticAnalysisCheck({})
        assert check.name == "static-analysis"

    def test_display_name(self):
        """Test check display name."""
        check = PythonStaticAnalysisCheck({})
        assert "mypy" in check.display_name.lower() or "Static" in check.display_name

    def test_depends_on(self):
        """Test check dependencies."""
        check = PythonStaticAnalysisCheck({})
        # Static analysis depends on lint-format being run first
        assert "python:lint-format" in check.depends_on

    def test_is_applicable_python_project(self, tmp_path):
        """Test is_applicable returns True for Python project."""
        (tmp_path / "main.py").touch()
        check = PythonStaticAnalysisCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_run_success(self, tmp_path):
        """Test run with no type errors."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="Success: no issues found", stderr="", duration=1.0
        )

        check = PythonStaticAnalysisCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_run_type_errors(self, tmp_path):
        """Test run with type errors."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=1,
            stdout="src/main.py:10: error: Incompatible types",
            stderr="",
            duration=1.0,
        )

        check = PythonStaticAnalysisCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED

    def test_run_finds_python_packages(self, tmp_path):
        """Test run finds Python packages when no standard dirs exist."""
        # Create a custom package (not src, lib, etc.)
        (tmp_path / "mypackage").mkdir()
        (tmp_path / "mypackage" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="Success: no issues found", stderr="", duration=1.0
        )

        check = PythonStaticAnalysisCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        # Verify mypackage was included in the command
        call_args = mock_runner.run.call_args
        assert "mypackage" in call_args[0][0]

    def test_run_falls_back_to_current_dir(self, tmp_path):
        """Test run uses '.' when no source dirs or packages found."""
        # Empty directory - no Python packages
        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=0, stdout="Success: no issues found", stderr="", duration=1.0
        )

        check = PythonStaticAnalysisCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        # Verify '.' was used as fallback
        call_args = mock_runner.run.call_args
        assert "." in call_args[0][0]

    def test_run_timeout(self, tmp_path):
        """Test run handles timeout."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        mock_runner = MagicMock()
        mock_runner.run.return_value = SubprocessResult(
            returncode=-1,
            stdout="",
            stderr="",
            duration=120.0,
            timed_out=True,
        )

        check = PythonStaticAnalysisCheck({}, runner=mock_runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "timed out" in result.error.lower()
