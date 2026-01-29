"""Tests for subprocess runner."""

from unittest.mock import MagicMock

import pytest

from slopbucket.subprocess.runner import (
    SubprocessResult,
    SubprocessRunner,
    get_runner,
    run_command,
)
from slopbucket.subprocess.validator import SecurityError


class TestSubprocessResult:
    """Tests for SubprocessResult class."""

    def test_success_true(self):
        """Test success property when returncode is 0."""
        result = SubprocessResult(
            returncode=0,
            stdout="output",
            stderr="",
            duration=1.0,
            timed_out=False,
        )
        assert result.success is True

    def test_success_false_returncode(self):
        """Test success property when returncode is non-zero."""
        result = SubprocessResult(
            returncode=1,
            stdout="",
            stderr="error",
            duration=1.0,
            timed_out=False,
        )
        assert result.success is False

    def test_success_false_timeout(self):
        """Test success property when timed out."""
        result = SubprocessResult(
            returncode=0,
            stdout="",
            stderr="",
            duration=10.0,
            timed_out=True,
        )
        assert result.success is False

    def test_output_combined(self):
        """Test output property combines stdout and stderr."""
        result = SubprocessResult(
            returncode=0,
            stdout="standard output",
            stderr="error output",
            duration=1.0,
        )
        assert "standard output" in result.output
        assert "error output" in result.output

    def test_output_stdout_only(self):
        """Test output with only stdout."""
        result = SubprocessResult(
            returncode=0,
            stdout="output",
            stderr="",
            duration=1.0,
        )
        assert result.output == "output"

    def test_output_empty(self):
        """Test output when both are empty."""
        result = SubprocessResult(
            returncode=0,
            stdout="",
            stderr="",
            duration=1.0,
        )
        assert result.output == ""


class TestSubprocessRunner:
    """Tests for SubprocessRunner class."""

    def test_init_default(self):
        """Test default initialization."""
        runner = SubprocessRunner()
        assert runner._default_timeout == SubprocessRunner.DEFAULT_TIMEOUT

    def test_init_custom_timeout(self):
        """Test custom timeout initialization."""
        runner = SubprocessRunner(default_timeout=60)
        assert runner._default_timeout == 60

    def test_init_timeout_capped(self):
        """Test that timeout is capped at MAX_TIMEOUT."""
        runner = SubprocessRunner(default_timeout=9999)
        assert runner._default_timeout == SubprocessRunner.MAX_TIMEOUT

    def test_run_simple_command(self):
        """Test running a simple command with whitelisted executable."""
        runner = SubprocessRunner()
        # Use python3 which is in the whitelist
        result = runner.run(["python3", "-c", "print('hello')"])

        assert result.success
        assert "hello" in result.stdout

    def test_run_with_cwd(self, tmp_path):
        """Test running command with working directory."""
        runner = SubprocessRunner()
        # Use ls which shows files in the cwd
        result = runner.run(["ls"], cwd=str(tmp_path))

        # Should succeed even in empty dir
        assert result.success

    def test_run_command_not_found(self):
        """Test running a command whose binary doesn't exist."""
        # Create a runner with a mock validator that allows anything
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock()  # Don't raise
        runner = SubprocessRunner(validator=mock_validator)

        result = runner.run(["nonexistent_command_xyz123"])

        assert not result.success
        assert (
            "not found" in result.stderr.lower() or "Command not found" in result.stderr
        )

    def test_run_with_timeout(self):
        """Test running command with timeout."""
        # Create a runner with a mock validator that allows anything
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock()  # Don't raise
        runner = SubprocessRunner(validator=mock_validator)

        # Use python3 sleep with 1 second timeout
        result = runner.run(["python3", "-c", "import time\ntime.sleep(10)"], timeout=1)

        assert result.timed_out
        assert not result.success

    def test_run_command_fails(self):
        """Test running a command that fails."""
        runner = SubprocessRunner()
        # python3 -c with invalid syntax will fail
        result = runner.run(["python3", "-c", "exit(1)"])

        assert not result.success
        assert result.returncode != 0

    def test_run_with_retry_success_first_try(self):
        """Test run_with_retry succeeds on first try."""
        runner = SubprocessRunner()
        result = runner.run_with_retry(
            ["python3", "-c", "print('hello')"], max_retries=2
        )

        assert result.success
        assert "hello" in result.stdout

    def test_run_with_retry_fails_all(self):
        """Test run_with_retry when all attempts fail."""
        runner = SubprocessRunner()
        result = runner.run_with_retry(
            ["python3", "-c", "exit(1)"],
            max_retries=1,
        )

        assert not result.success

    def test_is_running_not_tracked(self):
        """Test is_running for untracked PID."""
        runner = SubprocessRunner()
        assert runner.is_running(99999) is False

    def test_terminate_all_empty(self):
        """Test terminate_all with no running processes."""
        runner = SubprocessRunner()
        count = runner.terminate_all()
        assert count == 0

    def test_run_validation_fails(self):
        """Test that non-whitelisted commands raise SecurityError."""
        runner = SubprocessRunner()

        with pytest.raises(SecurityError):
            runner.run(["rm", "-rf", "/"])  # Not in whitelist

    def test_start_background(self):
        """Test starting a background process."""
        # Create a runner with a mock validator that allows anything
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock()  # Don't raise
        runner = SubprocessRunner(validator=mock_validator)

        process, pid = runner.start_background(
            ["python3", "-c", "import time\ntime.sleep(0.1)"]
        )

        assert pid > 0
        assert runner.is_running(pid) or process.poll() is not None

        # Cleanup
        process.wait()

    def test_run_captures_stderr(self):
        """Test that stderr is captured."""
        # Create a runner with a mock validator that allows anything
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock()  # Don't raise
        runner = SubprocessRunner(validator=mock_validator)

        result = runner.run(["python3", "-c", "import sys\nsys.stderr.write('error')"])

        assert "error" in result.stderr or "error" in result.output

    def test_run_with_custom_validator(self):
        """Test running with a custom validator."""
        # Create a validator that allows anything
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock()  # Don't raise

        runner = SubprocessRunner(validator=mock_validator)
        result = runner.run(["python3", "-c", "print('test')"])

        mock_validator.validate.assert_called_once()
        assert result.success


class TestSubprocessRunnerSingleton:
    """Tests for singleton pattern."""

    def test_get_runner_singleton(self):
        """Test that get_runner returns singleton."""
        import slopbucket.subprocess.runner as runner_module

        runner_module._default_runner = None

        runner1 = get_runner()
        runner2 = get_runner()

        assert runner1 is runner2

    def test_run_command_helper(self):
        """Test run_command convenience function."""
        result = run_command(["python3", "-c", "print('test')"])

        assert result.success
        assert "test" in result.stdout
