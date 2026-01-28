"""Tests for python_coverage.py — coverage threshold + diff-cover."""

import os
from unittest.mock import patch

from slopbucket.checks.python_coverage import (
    PythonCoverageCheck,
    PythonDiffCoverageCheck,
)
from slopbucket.result import CheckStatus
from slopbucket.subprocess_guard import SubprocessResult


def _ok(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(0, stdout, stderr, cmd=[])


def _fail(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(1, stdout, stderr, cmd=[])


class TestPythonCoverageCheck:
    """Validates global coverage threshold enforcement."""

    def setup_method(self) -> None:
        self.check = PythonCoverageCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "python-coverage"
        assert "80" in self.check.description

    def test_errors_when_no_coverage_xml(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.ERROR
            assert "coverage.xml not found" in result.output

    @patch("slopbucket.checks.python_coverage.run")
    def test_passes_with_sufficient_coverage(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            # Create a dummy coverage.xml
            with open(os.path.join(td, "coverage.xml"), "w") as f:
                f.write("<coverage/>")
            mock_run.return_value = _ok(stdout="TOTAL  100  0  100%")  # type: ignore[attr-defined]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.python_coverage.run")
    def test_fails_below_threshold(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "coverage.xml"), "w") as f:
                f.write("<coverage/>")
            mock_run.return_value = _fail(stdout="TOTAL  100  50  50%\nCoverage failure")  # type: ignore[attr-defined]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.FAILED


class TestPythonDiffCoverageCheck:
    """Validates diff coverage enforcement."""

    def setup_method(self) -> None:
        self.check = PythonDiffCoverageCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "python-diff-coverage"

    def test_errors_when_no_coverage_xml(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.ERROR

    @patch("slopbucket.checks.python_coverage.run")
    def test_passes_when_diff_coverage_sufficient(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "coverage.xml"), "w") as f:
                f.write("<coverage/>")
            mock_run.return_value = _ok(stdout="Diff coverage: 90%")  # type: ignore[attr-defined]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.python_coverage.run")
    def test_passes_when_no_diff(self, mock_run: object) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "coverage.xml"), "w") as f:
                f.write("<coverage/>")
            mock_run.return_value = _fail(stdout="No diff found")  # type: ignore[attr-defined]
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED
