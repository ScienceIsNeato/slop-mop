"""Tests for python_lint.py — Flake8 critical errors."""

from unittest.mock import patch

from slopbucket.checks.python_lint import PythonLintCheck
from slopbucket.result import CheckStatus
from slopbucket.subprocess_guard import SubprocessResult


def _ok(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(0, stdout, stderr, cmd=[])


def _fail(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(1, stdout, stderr, cmd=[])


class TestPythonLintCheck:
    """Validates lint check pass/fail/skip logic."""

    def setup_method(self) -> None:
        self.check = PythonLintCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "python-lint"
        assert "Flake8" in self.check.description

    @patch("slopbucket.checks.python_lint.PythonLintCheck._find_target_dirs")
    def test_skips_when_no_dirs(self, mock_dirs: object) -> None:
        mock_dirs.return_value = []  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/nonexistent")
        assert result.status == CheckStatus.SKIPPED

    @patch("slopbucket.checks.python_lint.run")
    @patch("slopbucket.checks.python_lint.PythonLintCheck._find_target_dirs")
    def test_passes_when_no_errors(self, mock_dirs: object, mock_run: object) -> None:
        mock_dirs.return_value = ["src"]  # type: ignore[attr-defined]
        mock_run.return_value = _ok()  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.python_lint.run")
    @patch("slopbucket.checks.python_lint.PythonLintCheck._find_target_dirs")
    def test_fails_with_lint_errors(self, mock_dirs: object, mock_run: object) -> None:
        mock_dirs.return_value = ["src"]  # type: ignore[attr-defined]
        mock_run.return_value = _fail(stdout="src/foo.py:1:1: F401 'os' imported but unused")  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.FAILED
        assert "F401" in result.output

    def test_critical_codes_defined(self) -> None:
        """All expected critical codes are in the list."""
        assert "E9" in self.check.CRITICAL_CODES
        assert "F82" in self.check.CRITICAL_CODES
        assert "F401" in self.check.CRITICAL_CODES
