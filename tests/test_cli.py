"""
Tests for the CLI entry point (setup.py).
"""

import subprocess
import sys
from pathlib import Path

SETUP_PY = str(Path(__file__).resolve().parent.parent / "setup.py")


class TestCLI:
    """Tests for command-line interface behavior."""

    def _run_cli(self, args: list) -> subprocess.CompletedProcess:
        """Helper to run setup.py as a subprocess."""
        return subprocess.run(
            [sys.executable, SETUP_PY] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_help_flag(self) -> None:
        result = self._run_cli(["--help"])
        assert result.returncode == 0
        assert "PROFILES" in result.stdout
        assert "EXAMPLES" in result.stdout
        assert "--checks" in result.stdout

    def test_list_flag(self) -> None:
        result = self._run_cli(["--list"])
        assert result.returncode == 0
        assert "python-format" in result.stdout
        assert "python-lint" in result.stdout
        assert "commit" in result.stdout

    def test_no_args_shows_error(self) -> None:
        result = self._run_cli([])
        assert result.returncode == 1
        assert "--checks" in result.stdout or "--checks" in result.stderr

    def test_unknown_check_returns_error(self) -> None:
        result = self._run_cli(["--checks", "totally_fake_check_xyz"])
        assert result.returncode == 1

    def test_valid_check_runs(self) -> None:
        """Running a real check completes (pass or fail depending on env)."""
        result = self._run_cli(["--checks", "python-format", "--no-parallel"])
        # Should complete without crashing (exit 0 or 1 depending on formatting state)
        assert result.returncode in (0, 1)
        assert "python-format" in result.stdout
