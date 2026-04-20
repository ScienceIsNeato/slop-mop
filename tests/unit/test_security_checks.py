"""Tests for security checks (bandit, semgrep, detect-secrets)."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from slopmop.checks.security import (
    EXCLUDED_DIRS,
    SecurityCheck,
    SecurityLocalCheck,
    SecuritySubResult,
)
from slopmop.core.result import CheckStatus


class TestSecuritySubResult:
    """Tests for SecuritySubResult dataclass."""

    def test_create_passing_result(self):
        """Test creating a passing sub-result."""
        result = SecuritySubResult("bandit", True, "No issues found")
        assert result.name == "bandit"
        assert result.passed is True
        assert result.findings == "No issues found"
        assert result.warned is False

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
        assert check.name == "vulnerability-blindness.py"

    def test_full_name(self):
        """Test full check name with category."""
        check = SecurityLocalCheck({})
        assert check.full_name == "myopia:vulnerability-blindness.py"

    def test_display_name(self):
        """Test display name."""
        check = SecurityLocalCheck({})
        assert "Security Scan" in check.display_name
        assert "bandit" in check.display_name

    def test_config_schema(self):
        """Test config schema includes expected fields."""
        check = SecurityLocalCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "config_file_path" in field_names
        assert "scanners" in field_names
        assert "exclude_dirs" in field_names

    def test_init_config_discovers_detect_secrets_and_bandit_files(self, tmp_path):
        (tmp_path / ".secrets.baseline").write_text("{}")
        (tmp_path / ".bandit").write_text("[bandit]\n")

        check = SecurityLocalCheck({})
        overrides = check.init_config(str(tmp_path))

        assert overrides["config_file_path"] == ".secrets.baseline"
        assert overrides["bandit_config_file"] == ".bandit"

    def test_init_config_detects_bandit_section_in_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.bandit]\nskips = ['B101']\n")

        check = SecurityLocalCheck({})
        overrides = check.init_config(str(tmp_path))

        assert overrides["bandit_config_file"] == "pyproject.toml"

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
        config_file = tmp_path / "bandit.yaml"
        config_file.write_text("# bandit config")
        check = SecurityLocalCheck({"bandit_config_file": str(config_file)})
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"results": []})
        mock_result.stderr = ""

        with patch.object(check, "_run_command", return_value=mock_result) as mock_run:
            check._run_bandit(str(tmp_path))

        # Check that config file was used
        call_args = mock_run.call_args[0][0]
        assert "--configfile" in call_args
        assert str(config_file) in call_args

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

        with patch("slopmop.checks.security.ThreadPoolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor_class.return_value.__enter__.return_value = mock_executor
            mock_futures = [MagicMock() for _ in passing_results]
            for future, result in zip(mock_futures, passing_results):
                future.result.return_value = result
            mock_executor.submit.side_effect = mock_futures

            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "myopia:vulnerability-blindness.py" in result.name

    def test_run_with_failures(self, tmp_path):
        """Test run() when one check fails."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = SecurityLocalCheck({})

        results = [
            SecuritySubResult("bandit", False, "HIGH: Issue found"),
            SecuritySubResult("semgrep", True, "OK"),
            SecuritySubResult("detect-secrets", True, "OK"),
        ]

        with patch("slopmop.checks.security.ThreadPoolExecutor") as mock_executor_class:
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

        with patch("slopmop.checks.security.ThreadPoolExecutor") as mock_executor_class:
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


class TestRunSemgrep:
    """Tests for _run_semgrep method."""

    def test_semgrep_no_issues(self, tmp_path):
        """Test _run_semgrep with no issues found."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_semgrep(str(tmp_path))

        assert result.name == "semgrep"
        assert result.passed is True
        assert "No issues found" in result.findings

    def test_semgrep_with_findings(self, tmp_path):
        """Test _run_semgrep with findings."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.stdout = json.dumps(
            {
                "results": [
                    {
                        "extra": {"severity": "ERROR", "message": "SQL injection risk"},
                        "path": "app.py",
                        "start": {"line": 25},
                    }
                ]
            }
        )
        mock_result.returncode = 1
        mock_result.stderr = ""

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_semgrep(str(tmp_path))

        assert result.passed is False
        assert "ERROR" in result.findings
        assert "SQL injection" in result.findings

    def test_semgrep_only_informational(self, tmp_path):
        """Test _run_semgrep ignores INFO findings."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.stdout = json.dumps(
            {
                "results": [
                    {
                        "extra": {
                            "severity": "INFO",
                            "message": "Consider refactoring",
                        },
                        "path": "app.py",
                        "start": {"line": 10},
                    }
                ]
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_semgrep(str(tmp_path))

        assert result.passed is True
        assert "Only informational" in result.findings

    def test_semgrep_no_results(self, tmp_path):
        """Test _run_semgrep with empty results."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.stdout = json.dumps({"results": []})

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_semgrep(str(tmp_path))

        assert result.passed is True

    def test_semgrep_json_error(self, tmp_path):
        """Test _run_semgrep handles JSON parse errors."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.stdout = "not valid json"
        mock_result.returncode = 1
        mock_result.stderr = "Some error"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_semgrep(str(tmp_path))

        assert result.passed is False


class TestRunDetectSecrets:
    """Tests for _run_detect_secrets method."""

    def test_detect_secrets_uses_post_filter_not_exclude_files_arg(self):
        """Exclude handling should avoid shell-sensitive regex arguments."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps({"results": {}})

        with patch.object(check, "_run_command", return_value=mock_result) as mock_run:
            check._run_detect_secrets("/tmp/project")

        call_args = mock_run.call_args[0][0]
        assert "--exclude-files" not in call_args

    def test_detect_secrets_path_exclude_filters_tests_dir(self):
        """Configured exclude dirs should be honored during result parsing."""
        check = SecurityLocalCheck({})
        assert check._is_path_excluded_for_detect_secrets("server/tests/test_auth.py")
        assert not check._is_path_excluded_for_detect_secrets("server/app/auth.py")

    def test_detect_secrets_no_findings(self, tmp_path):
        """Test _run_detect_secrets with no secrets found."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps({"results": {}})

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.name == "detect-secrets"
        assert result.passed is True
        assert "No secrets" in result.findings

    def test_detect_secrets_with_findings(self, tmp_path):
        """Test _run_detect_secrets with secrets found."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "config.py": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 5,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is False
        assert "config.py" in result.findings
        assert "Secret Keyword" in result.findings

    def test_detect_secrets_ignores_constants(self, tmp_path):
        """Test _run_detect_secrets ignores constants.py."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {"results": {"constants.py": [{"type": "High Entropy String"}]}}
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True  # constants.py is ignored

    def test_detect_secrets_ignores_known_generated_and_placeholder_noise(
        self, tmp_path
    ):
        """Generated metadata and placeholder defaults should be filtered."""
        check = SecurityLocalCheck({})
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "__init__.py").write_text(
            'secret_key = app.config.get("SECRET_KEY")\n'  # pragma: allowlist secret
            'if not secret_key or secret_key == "dev-secret-change-me":\n'  # pragma: allowlist secret
            'jwt_secret = "dev-jwt-secret"\n'  # pragma: allowlist secret
        )
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "client/.metadata": [
                        {"type": "Hex High Entropy String", "line_number": 7}
                    ],
                    "server/.env.example": [
                        {"type": "Basic Auth Credentials", "line_number": 3}
                    ],
                    "app/__init__.py": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 1,
                        },  # pragma: allowlist secret
                        {
                            "type": "Secret Keyword",
                            "line_number": 2,
                        },  # pragma: allowlist secret
                        {
                            "type": "Secret Keyword",
                            "line_number": 3,
                        },  # pragma: allowlist secret
                    ],
                    "app/config.py": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 10,
                        }  # pragma: allowlist secret
                    ],
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is False
        assert "app/config.py" in result.findings
        assert "client/.metadata" not in result.findings
        assert "server/.env.example" not in result.findings
        assert "app/__init__.py" not in result.findings

    def test_detect_secrets_ignores_paths_from_exclude_dirs(self, tmp_path):
        """Findings in excluded dirs should not fail the gate."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "server/tests/test_auth.py": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 3,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True

    def test_detect_secrets_ignores_root_flutter_ephemeral_paths(self, tmp_path):
        """Root-level Flutter iOS ephemeral artifacts should be filtered."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "ios/Flutter/ephemeral/generated.xcconfig": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 1,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True

    def test_detect_secrets_does_not_filter_latest_as_test_marker(self, tmp_path):
        """Substring like 'latest' should not be treated as test placeholder noise."""
        check = SecurityLocalCheck({})
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "config.py").write_text(
            'SECRET_KEY = "latest_production_key_abc123"\n'  # pragma: allowlist secret
        )
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "app/config.py": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 1,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is False
        assert "app/config.py" in result.findings

    def test_detect_secrets_ignores_git_sha_fields(self, tmp_path):
        """Manifest-style git SHA references should not be treated as secrets."""
        check = SecurityLocalCheck({})
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        manifest = scenarios_dir / "happy-path-small.json"
        manifest.write_text(
            "\n".join(
                [
                    '{"fixture_base_sha": "f6049f7840ea4be9de6db24a9813c1a8212e38c3"}',
                    '{"from_sha": "cc96da5f7c045a5b8652ce00b6ee074201673012"}',
                    '{"to_sha": "742a795a416749884426cf98dc4c694d1b1fb68e"}',
                ]
            )
            + "\n"
        )
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "scenarios/happy-path-small.json": [
                        {"type": "Hex High Entropy String", "line_number": 1},
                        {"type": "Hex High Entropy String", "line_number": 2},
                        {"type": "Hex High Entropy String", "line_number": 3},
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True

    def test_detect_secrets_ignores_is_placeholder_sha_assertions(self, tmp_path):
        """Helper assertions about SHAs should not trip detect-secrets."""
        check = SecurityLocalCheck({})
        helpers = tmp_path / "helpers.py"
        helpers.write_text(
            'assert not is_placeholder_sha("abcdef1234567890abcdef1234567890abcdef12")\n'
        )
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "helpers.py": [
                        {"type": "Hex High Entropy String", "line_number": 1}
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True

    def test_detect_secrets_ignores_git_sha_context_from_neighbor_lines(self, tmp_path):
        """Git SHA context can come from surrounding lines, not just the hit line."""
        check = SecurityLocalCheck({})
        helpers = tmp_path / "helpers.py"
        helpers.write_text(
            "\n".join(
                [
                    "branch = make_run_branch_name(",
                    '    "happy-path-small",',
                    '    "abcdef1234567890",',
                    '    "run01",',
                    ")",
                    'if args[0] == "rev-parse":',
                    '    return (0, "abc12345def", "")',
                    "head = _current_head(project_root)",
                    'Mock(return_value="deadbeef1234")',
                ]
            )
            + "\n"
        )
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "helpers.py": [
                        {"type": "Hex High Entropy String", "line_number": 3},
                        {"type": "Hex High Entropy String", "line_number": 7},
                        {"type": "Hex High Entropy String", "line_number": 9},
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True

    def test_safe_read_line_uses_cache_for_same_file(self, tmp_path):
        """Line lookup cache should avoid repeated file reads per path."""
        check = SecurityLocalCheck({})
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "config.py").write_text("line1\nline2\n")

        read_calls = {"count": 0}
        original_read_text = Path.read_text

        def _counting_read_text(self, *args, **kwargs):
            read_calls["count"] += 1
            return original_read_text(self, *args, **kwargs)

        with patch("pathlib.Path.read_text", new=_counting_read_text):
            cache: dict[str, list[str]] = {}
            first = check._safe_read_line(str(tmp_path), "app/config.py", 1, cache)
            second = check._safe_read_line(str(tmp_path), "app/config.py", 2, cache)

        assert first == "line1"
        assert second == "line2"
        assert read_calls["count"] == 1

    def test_detect_secrets_json_error(self, tmp_path):
        """Test _run_detect_secrets handles JSON errors."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "not json"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True  # Scan completed

    def test_detect_secrets_failure(self, tmp_path):
        """Test _run_detect_secrets with command failure."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.output = "Error running scan"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is False

    def test_detect_secrets_never_passes_real_baseline_flag(self, tmp_path):
        """detect-secrets scan must NOT receive the real .secrets.baseline as --baseline.

        Passing the real baseline causes detect-secrets to rewrite the file on
        every run (updated ``generated_at``), turning read-only validation into
        a commit obligation.  When a temp plugin-config file is used, ``--baseline``
        may be present but must point elsewhere.
        """
        baseline = tmp_path / ".secrets.baseline"
        baseline.write_text(
            json.dumps({"generated_at": "2026-01-01T00:00:00Z", "results": {}})
        )
        check = SecurityLocalCheck({"config_file_path": ".secrets.baseline"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps({"results": {}})
        captured_cmd: list[str] = []

        def _capture(cmd: list[str], **kwargs: Any) -> MagicMock:  # type: ignore[misc]
            captured_cmd.extend(cmd)
            return mock_result

        with patch.object(check, "_run_command", side_effect=_capture):
            check._run_detect_secrets(str(tmp_path))

        real_baseline_path = str(tmp_path / ".secrets.baseline")
        # baseline has no plugins_used/filters_used, so --baseline must be absent
        assert "--baseline" not in captured_cmd, (
            "No --baseline should be passed when the baseline has no "
            "plugins_used or filters_used — _create_plugin_config_baseline "
            "should have returned None and left the flag out."
        )

    def test_detect_secrets_baseline_file_not_modified(self, tmp_path):
        """Running the security check must NOT modify the .secrets.baseline file."""
        original_content = json.dumps(
            {"generated_at": "2026-01-01T00:00:00Z", "results": {}}, indent=2
        )
        baseline = tmp_path / ".secrets.baseline"
        baseline.write_text(original_content)
        check = SecurityLocalCheck({"config_file_path": ".secrets.baseline"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps({"results": {}})

        with patch.object(check, "_run_command", return_value=mock_result):
            check._run_detect_secrets(str(tmp_path))

        assert (
            baseline.read_text() == original_content
        ), ".secrets.baseline was modified during a read-only security scan"

    def test_detect_secrets_baseline_allowlist_suppresses_known_hashes(self, tmp_path):
        """Secrets already in the baseline allowlist should not be reported."""
        hashed = "abc123def456"  # pragma: allowlist secret
        baseline = tmp_path / ".secrets.baseline"
        baseline.write_text(
            json.dumps(
                {
                    "generated_at": "2026-01-01T00:00:00Z",
                    "results": {
                        "config.py": [
                            {
                                "type": "Secret Keyword",
                                "hashed_secret": hashed,
                                "line_number": 5,
                            }  # pragma: allowlist secret
                        ]
                    },
                }
            )
        )
        check = SecurityLocalCheck({"config_file_path": ".secrets.baseline"})
        mock_result = MagicMock()
        mock_result.success = True
        # Scan finds the same secret — but it's in the baseline so should be suppressed
        mock_result.output = json.dumps(
            {
                "results": {
                    "config.py": [
                        {
                            "type": "Secret Keyword",
                            "hashed_secret": hashed,
                            "line_number": 5,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True, "Secret already in baseline should be suppressed"

    def test_detect_secrets_new_secret_not_in_baseline_reported(self, tmp_path):
        """A new secret not in the baseline should still be reported."""
        known_hash = "aaaaaaaaaaaa"  # pragma: allowlist secret
        new_hash = "bbbbbbbbbbbb"  # pragma: allowlist secret
        baseline = tmp_path / ".secrets.baseline"
        baseline.write_text(
            json.dumps(
                {
                    "generated_at": "2026-01-01T00:00:00Z",
                    "results": {
                        "config.py": [
                            {
                                "type": "Secret Keyword",
                                "hashed_secret": known_hash,
                                "line_number": 3,
                            }  # pragma: allowlist secret
                        ]
                    },
                }
            )
        )
        check = SecurityLocalCheck({"config_file_path": ".secrets.baseline"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "config.py": [
                        {
                            "type": "Secret Keyword",
                            "hashed_secret": new_hash,
                            "line_number": 7,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is False
        assert "config.py" in result.findings

    def test_detect_secrets_path_dotslash_normalized(self, tmp_path):
        """Baseline key './config.py' must suppress a scan finding of 'config.py'."""
        hashed = "abc123def456"  # pragma: allowlist secret
        baseline = tmp_path / ".secrets.baseline"
        baseline.write_text(
            json.dumps(
                {
                    "generated_at": "2026-01-01T00:00:00Z",
                    "results": {
                        "./config.py": [
                            {
                                "type": "Secret Keyword",
                                "hashed_secret": hashed,
                                "line_number": 5,
                            }  # pragma: allowlist secret
                        ]
                    },
                }
            )
        )
        check = SecurityLocalCheck({"config_file_path": ".secrets.baseline"})
        mock_result = MagicMock()
        mock_result.success = True
        # Scan reports the same hash under bare path (no leading ./)
        mock_result.output = json.dumps(
            {
                "results": {
                    "config.py": [
                        {
                            "type": "Secret Keyword",
                            "hashed_secret": hashed,
                            "line_number": 5,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True, (
            "'./config.py' in baseline should match 'config.py' from scan report "
            "(path normalization strips leading './')"
        )

    def test_detect_secrets_plugin_config_passed_via_temp_baseline(self, tmp_path):
        """When the baseline has plugins_used, --baseline must point to a temp file.

        The real .secrets.baseline must not be passed because detect-secrets
        rewrites it; a throwaway temp file inside .slopmop/ carries the plugin
        config instead.
        """
        baseline_content = {
            "generated_at": "2026-01-01T00:00:00Z",
            "plugins_used": [{"name": "HexHighEntropyString", "hex_limit": 3.0}],
            "filters_used": [],
            "results": {},
        }
        baseline = tmp_path / ".secrets.baseline"
        baseline.write_text(json.dumps(baseline_content))

        check = SecurityLocalCheck({"config_file_path": ".secrets.baseline"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps({"results": {}})
        captured_cmd: list[str] = []

        def _capture(cmd: list[str], **kwargs: Any) -> MagicMock:  # type: ignore[misc]
            captured_cmd.extend(cmd)
            return mock_result

        with patch.object(check, "_run_command", side_effect=_capture):
            check._run_detect_secrets(str(tmp_path))

        assert (
            "--baseline" in captured_cmd
        ), "--baseline should be in cmd when baseline has plugins_used"
        idx = captured_cmd.index("--baseline")
        passed_path = captured_cmd[idx + 1]
        real_baseline = str(tmp_path / ".secrets.baseline")
        assert (
            passed_path != real_baseline
        ), "The real .secrets.baseline must never be the --baseline argument"
        # Temp file must have been cleaned up
        from pathlib import Path as _Path

        assert not _Path(
            passed_path
        ).exists(), "Temp plugin-config baseline must be deleted after the scan"
        # Real baseline must be unmodified
        assert json.loads(baseline.read_text()) == baseline_content


class TestSecurityCheck:
    """Tests for SecurityCheck (full security with pip-audit)."""

    def test_name(self):
        """Test check name."""
        check = SecurityCheck({})
        assert check.name == "dependency-risk.py"

    def test_full_name(self):
        """Test full check name with category."""
        check = SecurityCheck({})
        assert check.full_name == "myopia:dependency-risk.py"

    def test_display_name(self):
        """Test display name includes dependency scanning."""
        check = SecurityCheck({})
        assert "Security Audit" in check.display_name
        assert "pip-audit" in check.display_name

    def test_not_superseded_by_itself(self):
        """Dependency-risk is the superseding gate and must still run during scour."""
        check = SecurityCheck({})
        assert check.superseded_by is None

    def test_run_all_checks_passed(self, tmp_path):
        """Test run() when all checks including pip-audit pass."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = SecurityCheck({})

        passing_results = [
            SecuritySubResult("bandit", True, "OK"),
            SecuritySubResult("semgrep", True, "OK"),
            SecuritySubResult("detect-secrets", True, "OK"),
            SecuritySubResult("pip-audit", True, "OK"),
        ]

        with patch("slopmop.checks.security.ThreadPoolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor_class.return_value.__enter__.return_value = mock_executor
            mock_futures = [MagicMock() for _ in passing_results]
            for future, result in zip(mock_futures, passing_results):
                future.result.return_value = result
            mock_executor.submit.side_effect = mock_futures

            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "myopia:dependency-risk.py" in result.name

    def test_run_pip_audit_failure(self, tmp_path):
        """Test run() when pip-audit check fails."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = SecurityCheck({})

        results = [
            SecuritySubResult("bandit", True, "OK"),
            SecuritySubResult("semgrep", True, "OK"),
            SecuritySubResult("detect-secrets", True, "OK"),
            SecuritySubResult("pip-audit", False, "Vulnerable dependency found"),
        ]

        with patch("slopmop.checks.security.ThreadPoolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor_class.return_value.__enter__.return_value = mock_executor
            mock_futures = [MagicMock() for _ in results]
            for future, res in zip(mock_futures, results):
                future.result.return_value = res
            mock_executor.submit.side_effect = mock_futures

            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "pip-audit" in result.output

    def test_run_pip_audit_warned(self, tmp_path):
        """Test run() warns when only non-remediable pip-audit vulns exist."""
        (tmp_path / "app.py").write_text("print('hello')")
        check = SecurityCheck({})

        results = [
            SecuritySubResult("bandit", True, "OK"),
            SecuritySubResult("semgrep", True, "OK"),
            SecuritySubResult("detect-secrets", True, "OK"),
            SecuritySubResult(
                "pip-audit",
                True,
                "No fix versions available",
                warned=True,
            ),
        ]

        with patch("slopmop.checks.security.ThreadPoolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor_class.return_value.__enter__.return_value = mock_executor
            mock_futures = [MagicMock() for _ in results]
            for future, res in zip(mock_futures, results):
                future.result.return_value = res
            mock_executor.submit.side_effect = mock_futures

            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.WARNED
        assert "non-blocking risk" in result.error
        assert "No fix versions available" in result.output


class TestRunPipAudit:
    """Tests for _run_pip_audit method."""

    def test_pip_audit_no_vulnerabilities(self, tmp_path):
        """Test _run_pip_audit with no vulnerable dependencies."""
        check = SecurityCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = json.dumps(
            {"dependencies": [{"name": "requests", "version": "2.31.0", "vulns": []}]}
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_pip_audit(str(tmp_path))

        assert result.name == "pip-audit"
        assert result.passed is True
        assert "No vulnerable" in result.findings

    def test_pip_audit_with_vulnerabilities(self, tmp_path):
        """Test _run_pip_audit with vulnerabilities found."""
        check = SecurityCheck({})
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.stdout = json.dumps(
            {
                "dependencies": [
                    {
                        "name": "requests",
                        "version": "2.25.0",
                        "vulns": [
                            {
                                "id": "CVE-2023-1234",
                                "fix_versions": ["2.31.0"],
                            }
                        ],
                    }
                ]
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_pip_audit(str(tmp_path))

        assert result.passed is False
        assert "requests" in result.findings
        assert "CVE-2023-1234" in result.findings

    def test_pip_audit_with_no_fix_versions_warns(self, tmp_path):
        """No-fix advisories should warn without blocking the gate."""
        check = SecurityCheck({})
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.stdout = json.dumps(
            {
                "dependencies": [
                    {
                        "name": "pygments",
                        "version": "2.19.2",
                        "vulns": [
                            {
                                "id": "GHSA-5239-wwwm-4pmq",
                                "fix_versions": [],
                            }
                        ],
                    }
                ]
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_pip_audit(str(tmp_path))

        assert result.passed is True
        assert result.warned is True
        assert "No fix versions available" in result.findings
        assert "GHSA-5239-wwwm-4pmq" in result.findings

    def test_pip_audit_empty_dependencies(self, tmp_path):
        """Test _run_pip_audit with no dependencies listed."""
        check = SecurityCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = json.dumps({"dependencies": []})

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_pip_audit(str(tmp_path))

        assert result.passed is True

    def test_pip_audit_json_error(self, tmp_path):
        """Test _run_pip_audit handles JSON parse errors."""
        check = SecurityCheck({})
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.stdout = "Error running pip-audit"
        mock_result.output = "Error running pip-audit"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_pip_audit(str(tmp_path))

        assert result.passed is False

    def test_pip_audit_json_error_success(self, tmp_path):
        """Test _run_pip_audit JSON error on successful return."""
        check = SecurityCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = "not valid json"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_pip_audit(str(tmp_path))

        assert result.passed is True

    def test_pip_audit_uses_project_python(self, tmp_path):
        """pip-audit must use project Python, not sys.executable.

        Unlike bandit/detect-secrets (which scan source *files*),
        pip-audit audits installed *packages* — it needs the project's
        Python so it inspects the project's dependencies, not slop-mop's.

        Regression: Bugbot flagged that sys.executable was used, which
        audited slop-mop's own bundled packages instead of the project's.
        """
        # Create a fake project venv so get_project_python returns it
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        fake_python = venv_bin / "python"
        fake_python.write_text("#!/bin/sh")
        fake_python.chmod(0o755)

        check = SecurityCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = json.dumps({"dependencies": []})

        with patch.object(check, "_run_command", return_value=mock_result) as mock_cmd:
            check._run_pip_audit(str(tmp_path))

        # Verify the command's first element is the project Python, not sys.executable
        cmd_used = mock_cmd.call_args[0][0]
        assert cmd_used[0] == str(
            fake_python
        ), f"Expected project Python {fake_python}, got {cmd_used[0]}"
