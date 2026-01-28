"""Tests for python_type_check.py — Mypy strict mode."""

from unittest.mock import patch

from slopbucket.checks.python_type_check import PythonTypeCheck
from slopbucket.result import CheckStatus
from slopbucket.subprocess_guard import SubprocessResult


def _ok(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(0, stdout, stderr, cmd=[])


def _fail(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(1, stdout, stderr, cmd=[])


class TestPythonTypeCheck:
    """Validates type check pass/fail/skip logic."""

    def setup_method(self) -> None:
        self.check = PythonTypeCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "python-types"
        assert "Mypy" in self.check.description

    @patch("slopbucket.checks.python_type_check._find_source_packages")
    def test_skips_when_no_packages(self, mock_pkgs: object) -> None:
        mock_pkgs.return_value = []  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/nonexistent")
        assert result.status == CheckStatus.SKIPPED

    @patch("slopbucket.checks.python_type_check.run")
    @patch("slopbucket.checks.python_type_check._find_source_packages")
    def test_passes_when_types_clean(self, mock_pkgs: object, mock_run: object) -> None:
        mock_pkgs.return_value = ["mypackage"]  # type: ignore[attr-defined]
        mock_run.return_value = _ok(stdout="Success: no issues found")  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.python_type_check.run")
    @patch("slopbucket.checks.python_type_check._find_source_packages")
    def test_fails_with_type_errors(self, mock_pkgs: object, mock_run: object) -> None:
        mock_pkgs.return_value = ["mypackage"]  # type: ignore[attr-defined]
        mock_run.return_value = _fail(stdout="mypackage/foo.py:10: error: Missing return type")  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.FAILED
        assert "Missing return type" in result.output
