"""Tests for git hooks CLI — repo-level hooks and git_wrapper.sh shell behaviour.

Deep hooks (system-level install/uninstall) have moved to sm mutinize.
See tests/unit/test_mutinize.py for those tests.
"""

import importlib.resources
import os
import subprocess
from pathlib import Path

from slopmop.cli.hooks import SB_HOOK_MARKER, _hooks_status


class TestHooksStatus:
    """Tests for _hooks_status display paths."""

    def _make_repo(self, tmp_path: Path) -> tuple[Path, Path]:
        project_root = tmp_path / "repo"
        project_root.mkdir()
        hooks_dir = project_root / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        return project_root, hooks_dir

    def test_status_shows_sm_managed_hook(self, tmp_path: Path, capsys: object) -> None:
        """Status lists sm-managed hooks when the marker is present."""
        project_root, hooks_dir = self._make_repo(tmp_path)
        (hooks_dir / "pre-commit").write_text(f"#!/bin/sh\n{SB_HOOK_MARKER}\n")

        _hooks_status(project_root, hooks_dir)

        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "Slop-Mop-managed hooks" in out
        assert "pre-commit" in out

    def test_status_shows_foreign_hook(self, tmp_path: Path, capsys: object) -> None:
        """Status lists unmanaged hooks under 'Other hooks'."""
        project_root, hooks_dir = self._make_repo(tmp_path)
        (hooks_dir / "pre-push").write_text("#!/bin/sh\n# third-party hook\n")

        _hooks_status(project_root, hooks_dir)

        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "Other hooks" in out
        assert "pre-push" in out

    def test_status_no_hooks_installed(self, tmp_path: Path, capsys: object) -> None:
        """Status reports no hooks when hooks_dir is empty."""
        project_root, hooks_dir = self._make_repo(tmp_path)

        _hooks_status(project_root, hooks_dir)

        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "No commit hooks installed" in out

    def test_status_mentions_mutinize(self, tmp_path: Path, capsys: object) -> None:
        """Status output points to sm mutinize for system-wide intercepts."""
        project_root, hooks_dir = self._make_repo(tmp_path)

        _hooks_status(project_root, hooks_dir)

        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "mutinize" in out


_WRAPPER_PATH = str(
    importlib.resources.files("slopmop.data").joinpath("git_wrapper.sh")
)


def _run_wrapper(*args: str) -> "subprocess.CompletedProcess[str]":
    """Run git_wrapper.sh with a fake git that always succeeds."""
    import tempfile

    with tempfile.TemporaryDirectory() as fake_bin:
        fake_git = os.path.join(fake_bin, "git")
        with open(fake_git, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(fake_git, 0o755)
        env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}
        return subprocess.run(
            ["bash", _WRAPPER_PATH, *args],
            capture_output=True,
            text=True,
            env=env,
        )


class TestGitWrapperEndOfOptions:
    """Shell-level tests for the -- end-of-options separator in git_wrapper.sh."""

    def test_no_verify_flag_blocked(self) -> None:
        result = _run_wrapper("commit", "-m", "msg", "--no-verify")
        assert result.returncode == 1
        assert "bypass" in result.stdout.lower() or "STOP" in result.stdout

    def test_no_verify_after_double_dash_allowed(self) -> None:
        """Pathspec literally named '--no-verify' must not be blocked."""
        result = _run_wrapper("commit", "-m", "msg", "--", "--no-verify")
        assert result.returncode == 0

    def test_double_dash_passes_through(self) -> None:
        result = _run_wrapper("commit", "-m", "msg", "--")
        assert result.returncode == 0

    def test_normal_commit_allowed(self) -> None:
        result = _run_wrapper("commit", "-m", "normal message")
        assert result.returncode == 0
