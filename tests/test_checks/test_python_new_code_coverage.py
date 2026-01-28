"""Tests for python-new-code-coverage check and COMPARE_BRANCH env resolution."""

import os
from unittest.mock import patch

from slopbucket.checks.python_coverage import (
    PythonNewCodeCoverageCheck,
    _get_compare_branch,
)
from slopbucket.result import CheckStatus


class TestGetCompareBranch:
    """Validates COMPARE_BRANCH resolution precedence."""

    @patch.dict(os.environ, {"COMPARE_BRANCH": "dev"}, clear=True)
    def test_prefers_compare_branch_env(self) -> None:
        assert _get_compare_branch() == "dev"

    @patch.dict(
        os.environ,
        {"COMPARE_BRANCH": "dev", "GITHUB_BASE_REF": "main"},
        clear=True,
    )
    def test_compare_branch_overrides_github_base_ref(self) -> None:
        assert _get_compare_branch() == "dev"

    @patch.dict(os.environ, {"GITHUB_BASE_REF": "release/v2"}, clear=True)
    def test_falls_back_to_github_base_ref(self) -> None:
        assert _get_compare_branch() == "release/v2"

    @patch.dict(os.environ, {}, clear=True)
    def test_defaults_to_origin_main(self) -> None:
        assert _get_compare_branch() == "origin/main"


class TestPythonNewCodeCoverageCheck:
    """Validates new-code coverage check behavior."""

    def setup_method(self) -> None:
        self.check = PythonNewCodeCoverageCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "python-new-code-coverage"
        assert (
            "new" in self.check.description.lower()
            or "coverage" in self.check.description.lower()
        )

    def test_error_when_no_coverage_xml(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.ERROR
            assert "coverage.xml" in result.output

    @patch("slopbucket.checks.python_coverage.run")
    def test_passes_when_diff_cover_succeeds(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "coverage.xml"), "w") as f:
                f.write("<coverage></coverage>\n")
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=0,
                stdout="Diff coverage: 95%\n",
                stderr="",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED
            assert (
                "adequate" in result.output.lower()
                or "coverage" in result.output.lower()
            )

    @patch("slopbucket.checks.python_coverage.run")
    def test_fails_when_coverage_below_threshold(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "coverage.xml"), "w") as f:
                f.write("<coverage></coverage>\n")
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=1,
                stdout="Diff coverage: 45% (below 80% threshold)\n",
                stderr="",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.FAILED

    @patch("slopbucket.checks.python_coverage.run")
    def test_passes_when_no_diff(self, mock_run: object) -> None:
        import tempfile

        from slopbucket.subprocess_guard import SubprocessResult

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "coverage.xml"), "w") as f:
                f.write("<coverage></coverage>\n")
            mock_run.return_value = SubprocessResult(  # type: ignore[attr-defined]
                returncode=0,
                stdout="No diff to analyze\n",
                stderr="",
                cmd=[],
            )
            result = self.check.execute(working_dir=td)
            assert result.status == CheckStatus.PASSED
