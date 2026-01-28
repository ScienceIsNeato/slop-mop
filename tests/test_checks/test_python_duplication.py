"""Tests for python_duplication.py — jscpd copy-paste detection."""

from unittest.mock import patch

from slopbucket.checks.python_duplication import PythonDuplicationCheck
from slopbucket.result import CheckStatus
from slopbucket.subprocess_guard import SubprocessResult


def _ok(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(0, stdout, stderr, cmd=[])


def _fail(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(1, stdout, stderr, cmd=[])


class TestPythonDuplicationCheck:
    """Validates duplication check pass/fail logic."""

    def setup_method(self) -> None:
        self.check = PythonDuplicationCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "python-duplication"
        assert "5%" in self.check.description

    @patch("slopbucket.checks.python_duplication.run")
    def test_passes_within_threshold(self, mock_run: object) -> None:
        mock_run.return_value = _ok(stdout="Duplication: 3.2%")  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.python_duplication.run")
    def test_fails_above_threshold(self, mock_run: object) -> None:
        mock_run.return_value = _fail(stdout="Duplication: 8.5% (threshold: 5%)")  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.FAILED
