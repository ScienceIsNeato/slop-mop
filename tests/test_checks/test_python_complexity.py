"""Tests for python_complexity.py — Radon cyclomatic complexity."""

from unittest.mock import patch

from slopbucket.checks.python_complexity import PythonComplexityCheck
from slopbucket.result import CheckStatus
from slopbucket.subprocess_guard import SubprocessResult


def _ok(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(0, stdout, stderr, cmd=[])


def _fail(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(1, stdout, stderr, cmd=[])


class TestPythonComplexityCheck:
    """Validates complexity check pass/fail/skip logic."""

    def setup_method(self) -> None:
        self.check = PythonComplexityCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "python-complexity"
        assert "complexity" in self.check.description.lower()

    @patch(
        "slopbucket.checks.python_complexity.PythonComplexityCheck._find_target_dirs"
    )
    def test_skips_when_no_dirs(self, mock_dirs: object) -> None:
        mock_dirs.return_value = []  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/nonexistent")
        assert result.status == CheckStatus.SKIPPED

    @patch("slopbucket.checks.python_complexity.run")
    @patch(
        "slopbucket.checks.python_complexity.PythonComplexityCheck._find_target_dirs"
    )
    def test_passes_with_low_complexity(
        self, mock_dirs: object, mock_run: object
    ) -> None:
        mock_dirs.return_value = ["src"]  # type: ignore[attr-defined]
        mock_run.return_value = _ok(stdout="Average complexity: A (2.5)")  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.python_complexity.run")
    @patch(
        "slopbucket.checks.python_complexity.PythonComplexityCheck._find_target_dirs"
    )
    def test_fails_with_high_complexity(
        self, mock_dirs: object, mock_run: object
    ) -> None:
        mock_dirs.return_value = ["src"]  # type: ignore[attr-defined]
        radon_output = "- process_data - D (25)\n- handle_request - E (30)"
        mock_run.return_value = _ok(stdout=radon_output)  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.FAILED
        assert "process_data" in result.output

    def test_parse_violations_extracts_dplus(self) -> None:
        """Only D/E/F ranked functions are violations."""
        output = (
            "- func_a - A (3)\n- func_b - D (25)\n- func_c - C (15)\n- func_d - E (30)"
        )
        violations = self.check._parse_violations(output)
        assert len(violations) == 2
        assert any("func_b" in v for v in violations)
        assert any("func_d" in v for v in violations)
