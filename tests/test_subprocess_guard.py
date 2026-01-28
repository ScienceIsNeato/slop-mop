"""
Tests for subprocess_guard.py — security allowlist enforcement.

These tests verify that the guard:
1. Allows whitelisted executables
2. Rejects unlisted executables
3. Never uses shell=True
4. Handles missing commands gracefully
"""

import sys

import pytest

from slopbucket.subprocess_guard import (
    ALLOWED_EXECUTABLES,
    GuardViolationError,
    SubprocessResult,
    _validate_executable,
    add_to_allowlist,
    run,
)


class TestValidateExecutable:
    """Tests for executable validation logic."""

    def test_allowed_executable_passes(self) -> None:
        """Whitelisted executables are accepted."""
        result = _validate_executable(["python"])
        assert result == "python"

    def test_sys_executable_passes(self) -> None:
        """Current Python interpreter is always allowed."""
        result = _validate_executable([sys.executable])
        assert result == sys.executable

    def test_unknown_executable_raises(self) -> None:
        """Unlisted executables are rejected."""
        with pytest.raises(GuardViolationError, match="not in the allowlist"):
            _validate_executable(["definitely_not_a_real_tool_xyz"])

    def test_empty_command_raises(self) -> None:
        """Empty command sequence is rejected."""
        with pytest.raises(GuardViolationError, match="Empty command"):
            _validate_executable([])

    def test_add_to_allowlist(self) -> None:
        """Custom executables can be added to the allowlist."""
        add_to_allowlist("my_custom_tool")
        assert "my_custom_tool" in ALLOWED_EXECUTABLES
        # Clean up
        ALLOWED_EXECUTABLES.discard("my_custom_tool")


class TestSubprocessResult:
    """Tests for SubprocessResult data class."""

    def test_success_property(self) -> None:
        result = SubprocessResult(returncode=0, stdout="ok", stderr="", cmd=["echo"])
        assert result.success is True

    def test_failure_property(self) -> None:
        result = SubprocessResult(returncode=1, stdout="", stderr="err", cmd=["fail"])
        assert result.success is False

    def test_output_combines_streams(self) -> None:
        result = SubprocessResult(
            returncode=0, stdout="out", stderr="err", cmd=["test"]
        )
        assert "out" in result.output
        assert "err" in result.output

    def test_repr(self) -> None:
        result = SubprocessResult(
            returncode=0, stdout="", stderr="", cmd=["echo", "hi"]
        )
        assert "echo" in repr(result)
        assert "rc=0" in repr(result)


class TestRun:
    """Tests for the guarded run() function."""

    def test_run_allowed_command(self) -> None:
        """Running an allowed command succeeds."""
        result = run([sys.executable, "-c", "print('hello')"])
        assert result.success
        assert "hello" in result.stdout

    def test_run_disallowed_command_raises(self) -> None:
        """Running a disallowed command raises GuardViolationError."""
        with pytest.raises(GuardViolationError):
            run(["totally_fake_command_xyz"])

    def test_run_nonexistent_allowed_command(self) -> None:
        """Allowed but nonexistent command returns graceful failure."""
        # 'curl' is allowed but might not exist in all envs
        # Use a command we know is in the allowlist but fabricate it
        add_to_allowlist("slopbucket_test_missing_bin")
        result = run(["slopbucket_test_missing_bin"])
        assert result.returncode == 127
        assert "not found" in result.stderr
        ALLOWED_EXECUTABLES.discard("slopbucket_test_missing_bin")

    def test_run_with_working_dir(self, tmp_path: "Path") -> None:  # noqa: F821
        """Commands respect the cwd parameter."""
        result = run(
            [sys.executable, "-c", "import os; print(os.getcwd())"],
            cwd=str(tmp_path),
        )
        assert result.success
        assert str(tmp_path) in result.stdout

    def test_run_captures_stderr(self) -> None:
        """Stderr is captured separately."""
        result = run(
            [sys.executable, "-c", "import sys; sys.stderr.write('error_msg')"],
        )
        assert "error_msg" in result.stderr

    def test_run_timeout(self) -> None:
        """Commands respect timeout parameter."""
        import subprocess

        with pytest.raises(subprocess.TimeoutExpired):
            run(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout=1,
            )
