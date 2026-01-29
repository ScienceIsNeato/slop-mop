"""Tests for security checks (bandit, semgrep, detect-secrets)."""

import json
from unittest.mock import MagicMock, patch

from slopbucket.checks.security import (
    EXCLUDED_DIRS,
    SecurityLocalCheck,
    SecuritySubResult,
)
from slopbucket.core.result import CheckStatus


class TestSecuritySubResult:
    """Tests for SecuritySubResult dataclass."""

    def test_create_passing_result(self):
        """Test creating a passing sub-result."""
        result = SecuritySubResult("bandit", True, "No issues found")
        assert result.name == "bandit"
        assert result.passed is True
        assert result.findings == "No issues found"

    def test_create_failing_result(self):
        """Test creating a failing sub-result."""
        result = SecuritySubResult("semgrep", False, "HIGH: SQL injection found")
        assert result.name == "semgrep"
        assert result.passed is False
        assert "SQL injection" in result.findings


class TestSecurityLocalCheck:
    """Tests for SecurityLocalCheck."""

    def test_name(self):
        """Test check name."""
        check = SecurityLocalCheck({})
        assert check.name == "local"

    def test_full_name(self):
        """Test full check name with category."""
        check = SecurityLocalCheck({})
        assert check.full_name == "security:local"

    def test_display_name(self):
        """Test display name."""
        check = SecurityLocalCheck({})
        assert "Security Local" in check.display_name
        assert "bandit" in check.display_name

    def test_config_schema(self):
        """Test config schema includes expected fields."""
        check = SecurityLocalCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "scanners" in field_names
        assert "exclude_dirs" in field_names

    def test_is_applicable_with_python_files(self, tmp_path):
        """Test is_applicable returns True for Python projects."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = SecurityLocalCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_with_js_files(self, tmp_path):
        """Test is_applicable returns True for JavaScript projects."""
        (tmp_path / "app.js").write_text("console.log('hello')")
        check = SecurityLocalCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_with_ts_files(self, tmp_path):
        """Test is_applicable returns True for TypeScript projects."""
        (tmp_path / "app.ts").write_text("console.log('hello')")
        check = SecurityLocalCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_no_source_files(self, tmp_path):
        """Test is_applicable returns False when no source files."""
        (tmp_path / "README.md").write_text("# Hello")
        check = SecurityLocalCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_get_exclude_dirs_default(self):
        """Test default exclude dirs."""
        check = SecurityLocalCheck({})
        exclude = check._get_exclude_dirs()
        assert "venv" in exclude
        assert "node_modules" in exclude

    def test_get_exclude_dirs_from_config(self):
        """Test exclude dirs from config."""
        check = SecurityLocalCheck({"exclude_dirs": ["custom_dir", "other"]})
        exclude = check._get_exclude_dirs()
        assert "custom_dir" in exclude
        assert "other" in exclude

    def test_run_bandit_no_issues(self, tmp_path):
        """Test _run_bandit with no issues found."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"results": []})
        mock_result.stderr = ""

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_bandit(str(tmp_path))

        assert result.name == "bandit"
        assert result.passed is True
        assert "No HIGH/MEDIUM issues" in result.findings

    def test_run_bandit_with_high_issues(self, tmp_path):
        """Test _run_bandit with HIGH severity issues."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.stdout = json.dumps(
            {
                "results": [
                    {
                        "issue_severity": "HIGH",
                        "issue_text": "Hardcoded password",
                        "test_name": "B105",
                        "filename": "app.py",
                        "line_number": 10,
                    }
                ]
            }
        )
        mock_result.stderr = ""

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_bandit(str(tmp_path))

        assert result.name == "bandit"
        assert result.passed is False
        assert "HIGH" in result.findings
        assert "Hardcoded password" in result.findings

    def test_run_bandit_low_severity_ignored(self, tmp_path):
        """Test _run_bandit ignores LOW severity issues."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.stdout = json.dumps(
            {
                "results": [
                    {
                        "issue_severity": "LOW",
                        "issue_text": "Consider using hashlib",
                        "test_name": "B303",
                        "filename": "utils.py",
                        "line_number": 5,
                    }
                ]
            }
        )
        mock_result.stderr = ""

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_bandit(str(tmp_path))

        assert result.passed is True
        assert "No HIGH/MEDIUM issues" in result.findings

    def test_run_bandit_json_error(self, tmp_path):
        """Test _run_bandit handles JSON parse errors."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.stdout = "not valid json"
        mock_result.stderr = ""

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_bandit(str(tmp_path))

        assert result.passed is True  # No issues if can't parse

    def test_run_bandit_with_config_file(self, tmp_path):
        """Test _run_bandit uses config file if specified."""
        check = SecurityLocalCheck({"config_file_path": "/path/to/config.yaml"})
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"results": []})
        mock_result.stderr = ""

        with patch.object(check, "_run_command", return_value=mock_result) as mock_run:
            check._run_bandit(str(tmp_path))

        # Check that config file was used
        call_args = mock_run.call_args[0][0]
        assert "--configfile" in call_args
        assert "/path/to/config.yaml" in call_args

    def test_run_all_checks_passed(self, tmp_path):
        """Test run() when all checks pass."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = SecurityLocalCheck({})

        # Mock ThreadPoolExecutor to return passing results
        passing_results = [
            SecuritySubResult("bandit", True, "OK"),
            SecuritySubResult("semgrep", True, "OK"),
            SecuritySubResult("detect-secrets", True, "OK"),
        ]

        with patch(
            "slopbucket.checks.security.ThreadPoolExecutor"
        ) as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor_class.return_value.__enter__.return_value = mock_executor
            mock_futures = [MagicMock() for _ in passing_results]
            for future, result in zip(mock_futures, passing_results):
                future.result.return_value = result
            mock_executor.submit.side_effect = mock_futures

            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "security:local" in result.name

    def test_run_with_failures(self, tmp_path):
        """Test run() when one check fails."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = SecurityLocalCheck({})

        results = [
            SecuritySubResult("bandit", False, "HIGH: Issue found"),
            SecuritySubResult("semgrep", True, "OK"),
            SecuritySubResult("detect-secrets", True, "OK"),
        ]

        with patch(
            "slopbucket.checks.security.ThreadPoolExecutor"
        ) as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor_class.return_value.__enter__.return_value = mock_executor
            mock_futures = [MagicMock() for _ in results]
            for future, res in zip(mock_futures, results):
                future.result.return_value = res
            mock_executor.submit.side_effect = mock_futures

            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "1 security scanner(s) found issues" in result.error
        assert "bandit" in result.output

    def test_run_handles_exceptions(self, tmp_path):
        """Test run() handles scanner exceptions gracefully."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = SecurityLocalCheck({})

        with patch(
            "slopbucket.checks.security.ThreadPoolExecutor"
        ) as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor_class.return_value.__enter__.return_value = mock_executor
            mock_future = MagicMock()
            mock_future.result.side_effect = Exception("Scanner crashed")
            mock_executor.submit.return_value = mock_future

            result = check.run(str(tmp_path))

        # Should capture the exception as a failure
        assert result.status == CheckStatus.FAILED


class TestExcludedDirs:
    """Tests for EXCLUDED_DIRS constant."""

    def test_contains_venv(self):
        """Test venv is in excluded dirs."""
        assert "venv" in EXCLUDED_DIRS
        assert ".venv" in EXCLUDED_DIRS

    def test_contains_node_modules(self):
        """Test node_modules is in excluded dirs."""
        assert "node_modules" in EXCLUDED_DIRS

    def test_contains_tests(self):
        """Test tests dir is excluded."""
        assert "tests" in EXCLUDED_DIRS
