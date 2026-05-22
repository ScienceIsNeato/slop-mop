"""Tests for security checks (bandit, semgrep, detect-secrets)."""

import json
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
        (tmp_path / "requirements.txt").write_text("requests>=2.31.0\n")
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
        (tmp_path / "requirements.txt").write_text("requests>=2.25.0\n")
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
        (tmp_path / "requirements.txt").write_text("pygments>=2.19.2\n")
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
        (tmp_path / "requirements.txt").write_text("")
        check = SecurityCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = json.dumps({"dependencies": []})

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_pip_audit(str(tmp_path))

        assert result.passed is True

    def test_pip_audit_json_error(self, tmp_path):
        """Test _run_pip_audit handles JSON parse errors."""
        (tmp_path / "requirements.txt").write_text("requests>=2.31.0\n")
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
        (tmp_path / "requirements.txt").write_text("requests>=2.31.0\n")
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
        # With a project venv, environment-scan mode: no -r flag
        assert "-r" not in cmd_used

    def test_pip_audit_skipped_when_no_manifest(self, tmp_path):
        """When no project venv and no requirements files, pip-audit is skipped."""
        check = SecurityCheck({})
        with patch.object(check, "_run_command") as mock_cmd:
            result = check._run_pip_audit(str(tmp_path))

        mock_cmd.assert_not_called()
        assert result.passed is True
        assert "skipped" in result.findings

    def test_pip_audit_skipped_with_accurate_message_when_pyproject_but_no_req(
        self, tmp_path, monkeypatch
    ):
        """Accurate skip message when pyproject.toml exists but no requirements.txt."""
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        (tmp_path / "pyproject.toml").write_text("[build-system]\n")
        check = SecurityCheck({})
        with patch.object(check, "_run_command") as mock_cmd:
            result = check._run_pip_audit(str(tmp_path))

        mock_cmd.assert_not_called()
        assert result.passed is True
        assert "virtual environment" in result.findings
        assert "pyproject.toml" in result.findings

    def test_pip_audit_uses_requirements_flag_when_no_venv(self, tmp_path, monkeypatch):
        """When no project venv but requirements.txt exists, -r flag is used."""
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        req = tmp_path / "requirements.txt"
        req.write_text("requests>=2.31.0\n")
        check = SecurityCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = json.dumps({"dependencies": []})

        with patch.object(check, "_run_command", return_value=mock_result) as mock_cmd:
            check._run_pip_audit(str(tmp_path))

        cmd_used = mock_cmd.call_args[0][0]
        assert "-r" in cmd_used
        assert str(req) in cmd_used

    def test_pip_audit_uses_requirements_dir(self, tmp_path, monkeypatch):
        """Requirements files inside a requirements/ subdirectory are picked up."""
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        req_dir = tmp_path / "requirements"
        req_dir.mkdir()
        base = req_dir / "base.txt"
        base.write_text("requests>=2.31.0\n")
        check = SecurityCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = json.dumps({"dependencies": []})

        with patch.object(check, "_run_command", return_value=mock_result) as mock_cmd:
            check._run_pip_audit(str(tmp_path))

        cmd_used = mock_cmd.call_args[0][0]
        assert str(base) in cmd_used

    def test_pip_audit_skipped_when_virtual_env_set_but_no_project_manifest(
        self, tmp_path, monkeypatch
    ):
        """VIRTUAL_ENV pointing to slopmop's env must not be scanned for a non-Python project."""
        fake_venv = tmp_path / "fake_pipx_env"
        fake_venv_bin = fake_venv / "bin"
        fake_venv_bin.mkdir(parents=True)
        fake_python = fake_venv_bin / "python"
        fake_python.write_text("#!/bin/sh")
        fake_python.chmod(0o755)

        project = tmp_path / "ts_project"
        project.mkdir()

        monkeypatch.setenv("VIRTUAL_ENV", str(fake_venv))
        check = SecurityCheck({})
        with patch.object(check, "_run_command") as mock_cmd:
            result = check._run_pip_audit(str(project))

        mock_cmd.assert_not_called()
        assert result.passed is True
        assert "skipped" in result.findings

    def test_pip_audit_uses_virtual_env_when_project_has_manifest(
        self, tmp_path, monkeypatch
    ):
        """VIRTUAL_ENV is used for scanning when the project has a requirements.txt."""
        fake_venv = tmp_path / "project_env"
        fake_venv_bin = fake_venv / "bin"
        fake_venv_bin.mkdir(parents=True)
        fake_python = fake_venv_bin / "python"
        fake_python.write_text("#!/bin/sh")
        fake_python.chmod(0o755)

        project = tmp_path / "py_project"
        project.mkdir()
        (project / "requirements.txt").write_text("requests>=2.31.0\n")

        monkeypatch.setenv("VIRTUAL_ENV", str(fake_venv))
        check = SecurityCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = '{"dependencies": []}'
        with patch.object(check, "_run_command", return_value=mock_result) as mock_cmd:
            result = check._run_pip_audit(str(project))

        assert mock_cmd.called
        cmd_used = mock_cmd.call_args[0][0]
        assert "-r" not in cmd_used

    """Tests for SecurityCheck._find_requirements_files."""

    def test_finds_root_requirements_txt(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("")
        assert SecurityCheck._find_requirements_files(str(tmp_path)) == [str(req)]

    def test_finds_requirements_subdir(self, tmp_path):
        req_dir = tmp_path / "requirements"
        req_dir.mkdir()
        base = req_dir / "base.txt"
        dev = req_dir / "dev.txt"
        base.write_text("")
        dev.write_text("")
        found = SecurityCheck._find_requirements_files(str(tmp_path))
        assert str(base) in found
        assert str(dev) in found

    def test_returns_empty_when_no_manifests(self, tmp_path):
        assert SecurityCheck._find_requirements_files(str(tmp_path)) == []

    def test_root_and_subdir_both_returned(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("")
        req_dir = tmp_path / "requirements"
        req_dir.mkdir()
        (req_dir / "dev.txt").write_text("")
        found = SecurityCheck._find_requirements_files(str(tmp_path))
        assert len(found) == 2
