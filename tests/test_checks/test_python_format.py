"""Tests for python_format.py — Black + isort + autoflake."""

from unittest.mock import patch

from slopbucket.checks.python_format import PythonFormatCheck
from slopbucket.result import CheckStatus
from slopbucket.subprocess_guard import SubprocessResult


def _ok(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(0, stdout, stderr, cmd=[])


def _fail(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(1, stdout, stderr, cmd=[])


class TestPythonFormatCheck:
    """Validates formatting check pass/fail/skip logic."""

    def setup_method(self) -> None:
        self.check = PythonFormatCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "python-format"
        assert "Black" in self.check.description

    @patch("slopbucket.checks.python_format.PythonFormatCheck._find_target_dirs")
    def test_skips_when_no_dirs(self, mock_dirs: object) -> None:
        mock_dirs.return_value = []  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/nonexistent")
        assert result.status == CheckStatus.SKIPPED

    @patch("slopbucket.checks.python_format.run")
    @patch("slopbucket.checks.python_format.PythonFormatCheck._find_target_dirs")
    def test_passes_when_all_clean(self, mock_dirs: object, mock_run: object) -> None:
        mock_dirs.return_value = ["src"]  # type: ignore[attr-defined]
        mock_run.return_value = _ok()  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.python_format.run")
    @patch("slopbucket.checks.python_format.PythonFormatCheck._find_target_dirs")
    def test_fails_when_black_check_fails(
        self, mock_dirs: object, mock_run: object
    ) -> None:
        mock_dirs.return_value = ["src"]  # type: ignore[attr-defined]

        def side_effect(cmd: list, **kwargs: object) -> SubprocessResult:
            if "--check" in cmd:
                return _fail(stderr="would reformat src/foo.py")
            return _ok()

        mock_run.side_effect = side_effect  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.FAILED
        assert "black-check" in result.output

    @patch("slopbucket.checks.python_format.run")
    @patch("slopbucket.checks.python_format.PythonFormatCheck._find_target_dirs")
    def test_fails_when_isort_check_fails(
        self, mock_dirs: object, mock_run: object
    ) -> None:
        mock_dirs.return_value = ["src"]  # type: ignore[attr-defined]

        def side_effect(cmd: list, **kwargs: object) -> SubprocessResult:
            if "--check-only" in cmd:
                return _fail(stdout="ERROR: src/foo.py")
            return _ok()

        mock_run.side_effect = side_effect  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.FAILED
        assert "isort-check" in result.output
