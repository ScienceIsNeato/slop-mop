"""Tests for test type checks (smoke, integration, e2e)."""

import os
from unittest.mock import patch

from slopmop.checks.python.test_types import (
    E2ETestCheck,
    IntegrationTestCheck,
    SmokeTestCheck,
)
from slopmop.core.result import CheckStatus
from slopmop.subprocess.runner import SubprocessResult


def _make_result(output: str = "", returncode: int = 0):
    """Helper to create SubprocessResult with correct constructor."""
    return SubprocessResult(
        returncode=returncode,
        stdout=output,
        stderr="",
        duration=0.1,
        timed_out=False,
    )


class TestSmokeTestCheck:
    """Tests for SmokeTestCheck."""

    def test_name(self):
        """Test check name."""
        check = SmokeTestCheck({})
        assert check.name == "smoke-tests"

    def test_display_name(self):
        """Test display name."""
        check = SmokeTestCheck({})
        assert "Smoke Tests" in check.display_name
        assert "Selenium" in check.display_name

    def test_full_name(self):
        """Test full name includes category."""
        check = SmokeTestCheck({})
        assert check.full_name == "integration:smoke-tests"

    def test_config_schema(self):
        """Test config schema defines test_dir."""
        check = SmokeTestCheck({})
        schema = check.config_schema
        assert len(schema) == 1
        assert schema[0].name == "test_dir"
        assert schema[0].default == "tests/smoke"

    def test_is_applicable_no_directory(self, tmp_path):
        """Test is_applicable returns False without smoke dir."""
        check = SmokeTestCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_is_applicable_with_directory(self, tmp_path):
        """Test is_applicable returns True with smoke dir."""
        smoke_dir = tmp_path / "tests" / "smoke"
        smoke_dir.mkdir(parents=True)
        check = SmokeTestCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_run_no_smoke_directory(self, tmp_path):
        """Test run skips when no smoke directory."""
        check = SmokeTestCheck({})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.SKIPPED
        assert "No tests/smoke/ directory" in result.output

    def test_run_no_server_port(self, tmp_path):
        """Test run skips when no server port configured."""
        smoke_dir = tmp_path / "tests" / "smoke"
        smoke_dir.mkdir(parents=True)

        check = SmokeTestCheck({})

        with patch.dict(os.environ, {}, clear=True):
            # Ensure no TEST_PORT or PORT
            os.environ.pop("TEST_PORT", None)
            os.environ.pop("PORT", None)
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.SKIPPED
        assert "No server port configured" in result.output

    def test_run_tests_pass(self, tmp_path):
        """Test run passes when smoke tests pass."""
        smoke_dir = tmp_path / "tests" / "smoke"
        smoke_dir.mkdir(parents=True)

        check = SmokeTestCheck({})

        success_result = _make_result(output="3 passed in 5.0s", returncode=0)

        with patch.dict(os.environ, {"TEST_PORT": "8000"}):
            with patch.object(check, "_run_command", return_value=success_result):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "3 passed" in result.output

    def test_run_tests_fail(self, tmp_path):
        """Test run fails when smoke tests fail."""
        smoke_dir = tmp_path / "tests" / "smoke"
        smoke_dir.mkdir(parents=True)

        check = SmokeTestCheck({})

        fail_result = _make_result(output="1 failed, 2 passed", returncode=1)

        with patch.dict(os.environ, {"TEST_PORT": "8000"}):
            with patch.object(check, "_run_command", return_value=fail_result):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "Smoke tests failed" in result.error
        assert "port 8000" in result.fix_suggestion

    def test_run_collection_error(self, tmp_path):
        """Test run returns ERROR on collection failure."""
        smoke_dir = tmp_path / "tests" / "smoke"
        smoke_dir.mkdir(parents=True)

        check = SmokeTestCheck({})

        error_result = _make_result(
            output="ImportError: No module named 'selenium'", returncode=2
        )

        with patch.dict(os.environ, {"PORT": "5000"}):
            with patch.object(check, "_run_command", return_value=error_result):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.ERROR
        assert "collection error" in result.error
        assert "selenium" in result.fix_suggestion

    def test_detect_server_port_test_port(self):
        """Test _detect_server_port uses TEST_PORT."""
        check = SmokeTestCheck({})
        with patch.dict(os.environ, {"TEST_PORT": "9000"}):
            assert check._detect_server_port() == "9000"

    def test_detect_server_port_port_fallback(self):
        """Test _detect_server_port falls back to PORT."""
        check = SmokeTestCheck({})
        with patch.dict(os.environ, {"PORT": "8080"}, clear=True):
            os.environ.pop("TEST_PORT", None)
            assert check._detect_server_port() == "8080"


class TestIntegrationTestCheck:
    """Tests for IntegrationTestCheck."""

    def test_name(self):
        """Test check name."""
        check = IntegrationTestCheck({})
        assert check.name == "integration-tests"

    def test_display_name(self):
        """Test display name."""
        check = IntegrationTestCheck({})
        assert "Integration Tests" in check.display_name
        assert "database" in check.display_name.lower()

    def test_depends_on(self):
        """Test dependencies."""
        check = IntegrationTestCheck({})
        assert "integration:smoke-tests" in check.depends_on

    def test_is_applicable_no_directory(self, tmp_path):
        """Test is_applicable returns False without integration dir."""
        check = IntegrationTestCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_is_applicable_with_directory(self, tmp_path):
        """Test is_applicable returns True with integration dir."""
        integration_dir = tmp_path / "tests" / "integration"
        integration_dir.mkdir(parents=True)
        check = IntegrationTestCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_run_no_integration_directory(self, tmp_path):
        """Test run skips when no integration directory."""
        check = IntegrationTestCheck({})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.SKIPPED
        assert "No tests/integration/ directory" in result.output

    def test_run_no_database_url(self, tmp_path):
        """Test run skips when no DATABASE_URL."""
        integration_dir = tmp_path / "tests" / "integration"
        integration_dir.mkdir(parents=True)

        check = IntegrationTestCheck({})

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DATABASE_URL", None)
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.SKIPPED
        assert "DATABASE_URL not set" in result.output

    def test_run_tests_pass(self, tmp_path):
        """Test run passes when integration tests pass."""
        integration_dir = tmp_path / "tests" / "integration"
        integration_dir.mkdir(parents=True)

        check = IntegrationTestCheck({})

        success_result = _make_result(output="10 passed in 15.0s", returncode=0)

        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://test"}):
            with patch.object(check, "_run_command", return_value=success_result):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "10 passed" in result.output

    def test_run_tests_fail(self, tmp_path):
        """Test run fails when integration tests fail."""
        integration_dir = tmp_path / "tests" / "integration"
        integration_dir.mkdir(parents=True)

        check = IntegrationTestCheck({})

        fail_result = _make_result(output="2 failed, 8 passed", returncode=1)

        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://test"}):
            with patch.object(check, "_run_command", return_value=fail_result):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "Integration tests failed" in result.error
        assert "DATABASE_URL" in result.fix_suggestion

    def test_run_collection_error(self, tmp_path):
        """Test run returns ERROR on collection failure."""
        integration_dir = tmp_path / "tests" / "integration"
        integration_dir.mkdir(parents=True)

        check = IntegrationTestCheck({})

        error_result = _make_result(
            output="ModuleNotFoundError: No module named 'psycopg2'", returncode=2
        )

        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://test"}):
            with patch.object(check, "_run_command", return_value=error_result):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.ERROR
        assert "collection error" in result.error


class TestE2ETestCheck:
    """Tests for E2ETestCheck."""

    def test_name(self):
        """Test check name."""
        check = E2ETestCheck({})
        assert check.name == "e2e-tests"

    def test_display_name(self):
        """Test display name."""
        check = E2ETestCheck({})
        assert "E2E Tests" in check.display_name
        assert "Playwright" in check.display_name

    def test_depends_on(self):
        """Test dependencies."""
        check = E2ETestCheck({})
        assert "integration:integration-tests" in check.depends_on

    def test_config_schema(self):
        """Test config schema."""
        check = E2ETestCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]
        assert "test_dir" in field_names
        assert "test_command" in field_names

    def test_is_applicable_no_directory(self, tmp_path):
        """Test is_applicable returns False without e2e dir."""
        check = E2ETestCheck({})
        assert check.is_applicable(str(tmp_path)) is False

    def test_is_applicable_with_directory(self, tmp_path):
        """Test is_applicable returns True with e2e dir."""
        e2e_dir = tmp_path / "tests" / "e2e"
        e2e_dir.mkdir(parents=True)
        check = E2ETestCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_run_no_e2e_directory(self, tmp_path):
        """Test run skips when no e2e directory."""
        check = E2ETestCheck({})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.SKIPPED
        assert "No tests/e2e/ directory" in result.output

    def test_run_no_server_port(self, tmp_path):
        """Test run skips when no server port configured."""
        e2e_dir = tmp_path / "tests" / "e2e"
        e2e_dir.mkdir(parents=True)

        check = E2ETestCheck({})

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("E2E_PORT", None)
            os.environ.pop("TEST_PORT", None)
            os.environ.pop("PORT", None)
            result = check.run(str(tmp_path))

        assert result.status == CheckStatus.SKIPPED
        assert "port" in result.output.lower()

    def test_run_tests_pass(self, tmp_path):
        """Test run passes when e2e tests pass."""
        e2e_dir = tmp_path / "tests" / "e2e"
        e2e_dir.mkdir(parents=True)

        check = E2ETestCheck({})

        # First call: playwright probe (success), second call: test run (success)
        probe_result = _make_result(output="", returncode=0)
        success_result = _make_result(output="5 passed in 30.0s", returncode=0)

        with patch.dict(os.environ, {"TEST_PORT": "8000"}):
            with patch.object(
                check, "_run_command", side_effect=[probe_result, success_result]
            ):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "5 passed" in result.output

    def test_run_tests_fail(self, tmp_path):
        """Test run fails when e2e tests fail."""
        e2e_dir = tmp_path / "tests" / "e2e"
        e2e_dir.mkdir(parents=True)

        check = E2ETestCheck({})

        # First call: playwright probe (success), second call: test run (fail)
        probe_result = _make_result(output="", returncode=0)
        fail_result = _make_result(output="1 failed, 4 passed", returncode=1)

        with patch.dict(os.environ, {"E2E_PORT": "3000"}):
            with patch.object(
                check, "_run_command", side_effect=[probe_result, fail_result]
            ):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "E2E tests failed" in result.error
        assert "port 3000" in result.fix_suggestion

    def test_run_collection_error(self, tmp_path):
        """Test run returns ERROR on collection failure."""
        e2e_dir = tmp_path / "tests" / "e2e"
        e2e_dir.mkdir(parents=True)

        check = E2ETestCheck({})

        # First call: playwright probe (success), second call: collection error
        probe_result = _make_result(output="", returncode=0)
        error_result = _make_result(
            output="Error: Playwright not installed", returncode=2
        )

        with patch.dict(os.environ, {"PORT": "5000"}):
            with patch.object(
                check, "_run_command", side_effect=[probe_result, error_result]
            ):
                result = check.run(str(tmp_path))

        assert result.status == CheckStatus.ERROR
        assert "collection error" in result.error
        assert "playwright" in result.fix_suggestion.lower()

    def test_detect_server_port_e2e_env(self):
        """Test _detect_server_port uses E2E_PORT first."""
        check = E2ETestCheck({})
        with patch.dict(
            os.environ,
            {
                "E2E_PORT": "3000",
                "TEST_PORT": "8000",
                "PORT": "5000",
            },
        ):
            assert check._detect_server_port() == "3000"

    def test_detect_server_port_fallback(self):
        """Test _detect_server_port falls back to TEST_PORT then PORT."""
        check = E2ETestCheck({})
        with patch.dict(os.environ, {"TEST_PORT": "8000"}, clear=True):
            assert check._detect_server_port() == "8000"


class TestSummaryLine:
    """Tests for _summary_line static methods."""

    def test_smoke_summary_line_passed(self):
        """Test summary extraction from passed output."""
        output = "tests/smoke/test_login.py::test_login PASSED\n3 passed in 5.0s"
        result = SmokeTestCheck._summary_line(output)
        assert "3 passed" in result

    def test_smoke_summary_line_failed(self):
        """Test summary extraction from failed output."""
        output = "tests/smoke/test_x.py::test_x FAILED\n1 failed, 2 passed"
        result = SmokeTestCheck._summary_line(output)
        assert "failed" in result

    def test_smoke_summary_line_no_match(self):
        """Test summary fallback when no match."""
        output = "Running tests..."
        result = SmokeTestCheck._summary_line(output)
        assert "Smoke tests completed" in result

    def test_integration_summary_line(self):
        """Test integration check summary line."""
        output = "10 passed, 2 skipped in 12.0s"
        result = IntegrationTestCheck._summary_line(output)
        assert "10 passed" in result
