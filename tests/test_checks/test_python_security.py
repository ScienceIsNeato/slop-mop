"""Tests for python_security.py — Bandit, semgrep, detect-secrets."""

import json
from unittest.mock import patch

from slopbucket.checks.python_security import (
    PythonSecurityCheck,
    PythonSecurityLocalCheck,
    _run_bandit,
    _run_detect_secrets,
    _run_semgrep,
)
from slopbucket.result import CheckStatus
from slopbucket.subprocess_guard import SubprocessResult


def _ok(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(0, stdout, stderr, cmd=[])


def _fail(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(1, stdout, stderr, cmd=[])


class TestRunBandit:
    """Unit tests for bandit sub-check."""

    @patch("slopbucket.checks.python_security.run")
    def test_passes_when_clean(self, mock_run: object) -> None:
        mock_run.return_value = _ok()  # type: ignore[attr-defined]
        result = _run_bandit("/tmp")
        assert result.passed is True

    @patch("slopbucket.checks.python_security.run")
    def test_ignores_low_severity(self, mock_run: object) -> None:
        report = {
            "results": [
                {"issue_severity": "LOW", "issue_text": "minor", "test_name": "B101"}
            ]
        }
        mock_run.return_value = _fail(stdout=json.dumps(report))  # type: ignore[attr-defined]
        result = _run_bandit("/tmp")
        assert result.passed is True

    @patch("slopbucket.checks.python_security.run")
    def test_fails_on_high_severity(self, mock_run: object) -> None:
        report = {
            "results": [
                {
                    "issue_severity": "HIGH",
                    "issue_text": "SQL injection",
                    "test_name": "B608",
                    "filename": "app.py",
                    "line_number": 42,
                }
            ]
        }
        mock_run.return_value = _fail(stdout=json.dumps(report))  # type: ignore[attr-defined]
        result = _run_bandit("/tmp")
        assert result.passed is False
        assert "SQL injection" in result.findings


class TestRunSemgrep:
    """Unit tests for semgrep sub-check."""

    @patch("slopbucket.checks.python_security.run")
    def test_passes_when_clean(self, mock_run: object) -> None:
        mock_run.return_value = _ok(stdout=json.dumps({"results": []}))  # type: ignore[attr-defined]
        result = _run_semgrep("/tmp")
        assert result.passed is True

    @patch("slopbucket.checks.python_security.run")
    def test_fails_on_error_severity(self, mock_run: object) -> None:
        report = {
            "results": [
                {
                    "extra": {"severity": "ERROR", "message": "eval usage"},
                    "path": "app.py",
                    "start": {"line": 10},
                }
            ]
        }
        mock_run.return_value = _fail(stdout=json.dumps(report))  # type: ignore[attr-defined]
        result = _run_semgrep("/tmp")
        assert result.passed is False
        assert "eval usage" in result.findings


class TestRunDetectSecrets:
    """Unit tests for detect-secrets sub-check."""

    @patch("slopbucket.checks.python_security.run")
    def test_passes_when_no_secrets(self, mock_run: object) -> None:
        mock_run.return_value = _ok(stdout=json.dumps({"results": {}}))  # type: ignore[attr-defined]
        result = _run_detect_secrets("/tmp")
        assert result.passed is True

    @patch("slopbucket.checks.python_security.run")
    def test_fails_on_detected_secret(self, mock_run: object) -> None:
        report = {"results": {"config.py": [{"type": "AWS Access Key"}]}}
        mock_run.return_value = _ok(stdout=json.dumps(report))  # type: ignore[attr-defined]
        result = _run_detect_secrets("/tmp")
        assert result.passed is False
        assert "AWS Access Key" in result.findings


class TestPythonSecurityLocalCheck:
    """Integration of sub-checks into the local security gate."""

    def setup_method(self) -> None:
        self.check = PythonSecurityLocalCheck()

    def test_name_and_description(self) -> None:
        assert self.check.name == "python-security-local"
        assert "bandit" in self.check.description

    @patch("slopbucket.checks.python_security.run")
    def test_passes_when_all_subchecks_pass(self, mock_run: object) -> None:
        # All tools return success — detect-secrets expects results as dict, others as list
        def side_effect(cmd: list, **kwargs: object) -> SubprocessResult:
            if "detect_secrets" in str(cmd):
                return _ok(stdout=json.dumps({"results": {}}))
            return _ok(stdout=json.dumps({"results": []}))

        mock_run.side_effect = side_effect  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.PASSED

    @patch("slopbucket.checks.python_security.run")
    def test_fails_when_any_subcheck_fails(self, mock_run: object) -> None:
        report = {
            "results": [
                {
                    "issue_severity": "HIGH",
                    "issue_text": "Injection risk",
                    "test_name": "B608",
                    "filename": "x.py",
                    "line_number": 1,
                }
            ]
        }

        def side_effect(cmd: list, **kwargs: object) -> SubprocessResult:
            if "bandit" in str(cmd):
                return _fail(stdout=json.dumps(report))
            return _ok(stdout=json.dumps({"results": []}))

        mock_run.side_effect = side_effect  # type: ignore[attr-defined]
        result = self.check.execute(working_dir="/tmp")
        assert result.status == CheckStatus.FAILED


class TestPythonSecurityCheck:
    """Full security check including safety."""

    def test_name_includes_full(self) -> None:
        check = PythonSecurityCheck()
        assert check.name == "python-security"
        assert "full" in check.description
