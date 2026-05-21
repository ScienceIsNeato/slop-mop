"""Tests for deep hooks — system-level git wrapper install/uninstall."""

import argparse
import importlib.resources
import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from slopmop.cli.hooks import (
    DEEP_HOOK_MARKER,
    DEEP_HOOKS_CONFIRM_PHRASE,
    SB_HOOK_MARKER,
    _deep_hooks_install,
    _deep_hooks_uninstall,
    _deep_rc_candidates,
    _get_deep_rc_files,
    _hooks_status,
    _rc_has_marker,
    cmd_commit_hooks,
)


class TestDeepHooks:
    """Tests for system-level git wrapper (deep hooks)."""

    def _fake_home(self, tmp_path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        return fake_home

    def test_install_no_confirmation_returns_1(self, tmp_path, capsys):
        """Deep install without phrase prints warning and returns 1."""
        result = _deep_hooks_install(confirm="")
        assert result == 1
        out = capsys.readouterr().out
        assert "system-wide" in out
        assert DEEP_HOOKS_CONFIRM_PHRASE in out

    def test_install_wrong_phrase_blocked(self, capsys):
        """Deep install with wrong confirmation phrase is blocked."""
        result = _deep_hooks_install(confirm="sure yeah do it")
        assert result == 1

    def test_install_creates_wrapper_and_alias(self, tmp_path, capsys):
        """Correct phrase creates wrapper binary and appends alias to rc file."""
        fake_home = self._fake_home(tmp_path)
        fake_rc = fake_home / ".zshrc"
        fake_rc.write_text("# existing content\n")
        fake_slopmop = fake_home / ".slopmop"
        fake_wrapper = fake_slopmop / "bin" / "git_wrapper.sh"

        with (
            patch("slopmop.cli.hooks._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._get_deep_rc_files", return_value=[fake_rc]),
        ):
            result = _deep_hooks_install(confirm=DEEP_HOOKS_CONFIRM_PHRASE)

        assert result == 0
        assert fake_wrapper.exists()
        assert fake_wrapper.stat().st_mode & stat.S_IXUSR
        rc_text = fake_rc.read_text()
        assert DEEP_HOOK_MARKER in rc_text
        assert 'alias git="$HOME/.slopmop/bin/git_wrapper.sh"' in rc_text
        assert "# existing content" in rc_text  # original content preserved

    def test_install_idempotent_same_content(self, tmp_path, capsys):
        """Second install with same wrapper content skips write; alias already present skipped."""
        fake_home = self._fake_home(tmp_path)
        fake_slopmop = fake_home / ".slopmop"
        fake_wrapper = fake_slopmop / "bin" / "git_wrapper.sh"
        fake_wrapper.parent.mkdir(parents=True)
        real_bytes = (
            importlib.resources.files("slopmop.data")
            .joinpath("git_wrapper.sh")
            .read_bytes()
        )
        fake_wrapper.write_bytes(real_bytes)
        fake_wrapper.chmod(0o755)

        fake_rc = fake_home / ".zshrc"
        fake_rc.write_text(
            f"# before\n{DEEP_HOOK_MARKER}\nalias git=...\n# END SLOP-MOP DEEP\n"
        )

        with (
            patch("slopmop.cli.hooks._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._get_deep_rc_files", return_value=[fake_rc]),
        ):
            result = _deep_hooks_install(confirm=DEEP_HOOKS_CONFIRM_PHRASE)

        assert result == 0
        out = capsys.readouterr().out
        assert "already up to date" in out
        assert "alias already present" in out

    def test_install_updates_stale_wrapper(self, tmp_path, capsys):
        """Second install with different wrapper content overwrites and reports updated."""
        fake_home = self._fake_home(tmp_path)
        fake_slopmop = fake_home / ".slopmop"
        fake_wrapper = fake_slopmop / "bin" / "git_wrapper.sh"
        fake_wrapper.parent.mkdir(parents=True)
        fake_wrapper.write_bytes(b"# old version\n")
        fake_wrapper.chmod(0o755)

        fake_rc = fake_home / ".zshrc"
        fake_rc.write_text("# before\n")

        with (
            patch("slopmop.cli.hooks._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._get_deep_rc_files", return_value=[fake_rc]),
        ):
            result = _deep_hooks_install(confirm=DEEP_HOOKS_CONFIRM_PHRASE)

        assert result == 0
        out = capsys.readouterr().out
        assert "Updated" in out
        real_bytes = (
            importlib.resources.files("slopmop.data")
            .joinpath("git_wrapper.sh")
            .read_bytes()
        )
        assert fake_wrapper.read_bytes() == real_bytes

    def test_uninstall_removes_wrapper(self, tmp_path, capsys):
        """Deep uninstall removes git_wrapper.sh from ~/.slopmop/bin/."""
        fake_home = self._fake_home(tmp_path)
        fake_slopmop = fake_home / ".slopmop"
        fake_wrapper = fake_slopmop / "bin" / "git_wrapper.sh"
        fake_wrapper.parent.mkdir(parents=True)
        fake_wrapper.write_bytes(b"#!/bin/bash\n")

        with (
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._deep_rc_candidates", return_value=[]),
        ):
            result = _deep_hooks_uninstall()

        assert result == 0
        assert not fake_wrapper.exists()
        assert "Removed" in capsys.readouterr().out

    def test_uninstall_strips_alias_block_from_rc(self, tmp_path, capsys):
        """Deep uninstall removes the marker block without touching surrounding content."""
        fake_home = self._fake_home(tmp_path)
        fake_rc = fake_home / ".zshrc"
        fake_rc.write_text(
            "# before\n"
            f"{DEEP_HOOK_MARKER}\n"
            'alias git="$HOME/.slopmop/bin/git_wrapper.sh"\n'
            "# END SLOP-MOP DEEP\n"
            "# after\n"
        )
        fake_wrapper = fake_home / ".slopmop" / "bin" / "git_wrapper.sh"

        with (
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._deep_rc_candidates", return_value=[fake_rc]),
        ):
            result = _deep_hooks_uninstall()

        assert result == 0
        rc_text = fake_rc.read_text()
        assert DEEP_HOOK_MARKER not in rc_text
        assert "alias git" not in rc_text
        assert "# before" in rc_text
        assert "# after" in rc_text

    def test_uninstall_no_wrapper_no_alias_is_clean(self, tmp_path, capsys):
        """Deep uninstall on a clean machine exits cleanly."""
        fake_wrapper = tmp_path / "nonexistent" / "git_wrapper.sh"

        with (
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._deep_rc_candidates", return_value=[]),
        ):
            result = _deep_hooks_uninstall()

        assert result == 0
        assert "not found" in capsys.readouterr().out

    def test_cmd_commit_hooks_deep_requires_confirm(self, tmp_path, capsys):
        """cmd_commit_hooks install --deep without --confirm returns 1."""
        (tmp_path / ".git").mkdir()
        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="install",
            hook_verb="swab",
            deep=True,
            confirm="",
        )
        result = cmd_commit_hooks(args)
        assert result == 1
        assert "confirm" in capsys.readouterr().out.lower()

    def test_cmd_commit_hooks_deep_with_confirm_succeeds(self, tmp_path, capsys):
        """cmd_commit_hooks install --deep with correct phrase installs both."""
        (tmp_path / ".git").mkdir()
        fake_slopmop = tmp_path / ".slopmop_home" / ".slopmop"
        fake_wrapper = fake_slopmop / "bin" / "git_wrapper.sh"
        fake_rc = tmp_path / ".zshrc"
        fake_rc.write_text("")

        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="install",
            hook_verb="swab",
            deep=True,
            confirm=DEEP_HOOKS_CONFIRM_PHRASE,
        )

        with (
            patch("slopmop.cli.hooks._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._get_deep_rc_files", return_value=[fake_rc]),
        ):
            result = cmd_commit_hooks(args)

        assert result == 0
        assert (tmp_path / ".git" / "hooks" / "pre-commit").exists()
        assert fake_wrapper.exists()

    def test_uninstall_missing_end_marker_leaves_file_unchanged(self, tmp_path, capsys):
        """Uninstall with a missing end marker leaves the rc file unchanged."""
        fake_home = self._fake_home(tmp_path)
        fake_rc = fake_home / ".zshrc"
        original_content = (
            "# before\n"
            f"{DEEP_HOOK_MARKER}\n"
            'alias git="$HOME/.slopmop/bin/git_wrapper.sh"\n'
            "# after\n"
        )
        fake_rc.write_text(original_content)
        fake_wrapper = fake_home / ".slopmop" / "bin" / "git_wrapper.sh"

        with (
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._deep_rc_candidates", return_value=[fake_rc]),
        ):
            result = _deep_hooks_uninstall()

        assert result == 0
        assert fake_rc.read_text() == original_content
        assert "skipping" in capsys.readouterr().out.lower()

    def test_install_already_up_to_date_still_sets_exec_bit(self, tmp_path, capsys):
        """Install with matching content still ensures the wrapper is executable."""
        import importlib.resources

        fake_home = self._fake_home(tmp_path)
        fake_slopmop = fake_home / ".slopmop"
        fake_wrapper = fake_slopmop / "bin" / "git_wrapper.sh"
        fake_wrapper.parent.mkdir(parents=True)
        real_bytes = (
            importlib.resources.files("slopmop.data")
            .joinpath("git_wrapper.sh")
            .read_bytes()
        )
        fake_wrapper.write_bytes(real_bytes)
        fake_wrapper.chmod(0o644)  # intentionally no +x

        fake_rc = fake_home / ".zshrc"
        fake_rc.write_text(
            f"# before\n{DEEP_HOOK_MARKER}\nalias git=...\n# END SLOP-MOP DEEP\n"
        )

        with (
            patch("slopmop.cli.hooks._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._get_deep_rc_files", return_value=[fake_rc]),
        ):
            result = _deep_hooks_install(confirm=DEEP_HOOKS_CONFIRM_PHRASE)

        assert result == 0
        assert fake_wrapper.stat().st_mode & stat.S_IXUSR

    def test_cmd_commit_hooks_deep_uninstall_outside_git_repo(self, tmp_path, capsys):
        """cmd_commit_hooks uninstall --deep works even outside a git repo."""
        fake_wrapper = tmp_path / ".slopmop" / "bin" / "git_wrapper.sh"
        fake_wrapper.parent.mkdir(parents=True)
        fake_wrapper.write_bytes(b"#!/bin/bash\n")

        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="uninstall",
            hook_verb="swab",
            deep=True,
            confirm="",
        )

        with (
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._deep_rc_candidates", return_value=[]),
        ):
            result = cmd_commit_hooks(args)

        assert result == 0
        assert not fake_wrapper.exists()

    def test_cmd_commit_hooks_deep_install_proceeds_despite_foreign_hook(
        self, tmp_path, capsys
    ):
        """cmd_commit_hooks install --deep runs deep install even if hook install fails."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir()
        foreign_hook = hooks_dir / "pre-commit"
        foreign_hook.write_text("#!/bin/sh\n# third-party hook\n")

        fake_slopmop = tmp_path / ".slopmop_home" / ".slopmop"
        fake_wrapper = fake_slopmop / "bin" / "git_wrapper.sh"
        fake_rc = tmp_path / ".zshrc"
        fake_rc.write_text("")

        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="install",
            hook_verb="swab",
            deep=True,
            confirm=DEEP_HOOKS_CONFIRM_PHRASE,
        )

        with (
            patch("slopmop.cli.hooks._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._get_deep_rc_files", return_value=[fake_rc]),
        ):
            result = cmd_commit_hooks(args)

        assert result == 1  # hook install failed due to foreign hook
        assert fake_wrapper.exists()  # but deep install still ran


class TestRcHasMarker:
    """Tests for the _rc_has_marker helper."""

    def test_returns_false_on_oserror(self, tmp_path: Path) -> None:
        """An unreadable file returns False instead of raising."""
        rc = tmp_path / "rc"
        rc.write_text("# content")
        rc.chmod(0o000)
        try:
            result = _rc_has_marker(rc)
        finally:
            rc.chmod(0o644)
        assert result is False


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

        fake_wrapper = tmp_path / "nonexistent"
        with patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper):
            _hooks_status(project_root, hooks_dir)

        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "Slop-Mop-managed hooks" in out
        assert "pre-commit" in out

    def test_status_shows_foreign_hook(self, tmp_path: Path, capsys: object) -> None:
        """Status lists unmanaged hooks under 'Other hooks'."""
        project_root, hooks_dir = self._make_repo(tmp_path)
        (hooks_dir / "pre-push").write_text("#!/bin/sh\n# third-party hook\n")

        fake_wrapper = tmp_path / "nonexistent"
        with patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper):
            _hooks_status(project_root, hooks_dir)

        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "Other hooks" in out
        assert "pre-push" in out

    def test_status_no_hooks_installed(self, tmp_path: Path, capsys: object) -> None:
        """Status reports no hooks when hooks_dir is empty."""
        project_root, hooks_dir = self._make_repo(tmp_path)

        fake_wrapper = tmp_path / "nonexistent"
        with patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper):
            _hooks_status(project_root, hooks_dir)

        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "No commit hooks installed" in out

    def test_status_shows_wrapper_installed(
        self, tmp_path: Path, capsys: object
    ) -> None:
        """Status reports wrapper path when it exists."""
        project_root, hooks_dir = self._make_repo(tmp_path)
        fake_wrapper = tmp_path / "git_wrapper.sh"
        fake_wrapper.write_bytes(b"#!/bin/bash\n")
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        with (
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch.object(Path, "home", return_value=fake_home),
        ):
            _hooks_status(project_root, hooks_dir)

        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "git_wrapper.sh installed at" in out

    def test_status_shows_alias_active(self, tmp_path: Path, capsys: object) -> None:
        """Status reports alias active when rc file contains the marker."""
        project_root, hooks_dir = self._make_repo(tmp_path)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        fake_rc = fake_home / ".zshrc"
        fake_rc.write_text(f"{DEEP_HOOK_MARKER}\n")
        fake_wrapper = tmp_path / "nonexistent"

        with (
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch.object(Path, "home", return_value=fake_home),
        ):
            _hooks_status(project_root, hooks_dir)

        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "Shell alias active in" in out


class TestGetDeepRcFiles:
    """Tests for _get_deep_rc_files shell detection."""

    def test_bash_shell_returns_bash_files(self, tmp_path: Path) -> None:
        """bash shell yields .bashrc and .bash_profile."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with (
            patch.dict(os.environ, {"SHELL": "/bin/bash"}),
            patch.object(Path, "home", return_value=fake_home),
        ):
            result = _get_deep_rc_files()
        names = [p.name for p in result]
        assert any("bash" in n for n in names)

    def test_other_shell_returns_zsh_and_bash(self, tmp_path: Path) -> None:
        """Unknown shell yields both .zshrc and .bashrc candidates."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with (
            patch.dict(os.environ, {"SHELL": "/usr/bin/fish"}),
            patch.object(Path, "home", return_value=fake_home),
        ):
            result = _get_deep_rc_files()
        names = [p.name for p in result]
        assert ".zshrc" in names or ".bashrc" in names

    def test_returns_first_candidate_when_none_exist(self, tmp_path: Path) -> None:
        """Falls back to first candidate when no rc files exist on disk."""
        fake_home = tmp_path / "empty_home"
        fake_home.mkdir()
        with (
            patch.dict(os.environ, {"SHELL": "/bin/zsh"}),
            patch.object(Path, "home", return_value=fake_home),
        ):
            result = _get_deep_rc_files()
        assert len(result) == 1
        assert result[0].name == ".zshrc"

    def test_deep_rc_candidates_returns_four_paths(self) -> None:
        """_deep_rc_candidates returns exactly four standard rc paths."""
        result = _deep_rc_candidates()
        names = [p.name for p in result]
        assert ".zshrc" in names
        assert ".bashrc" in names
        assert len(result) == 4


class TestDeepHooksInstallErrors:
    """Tests for OSError paths in _deep_hooks_install."""

    def _mock_wrapper(self, **attrs: object) -> MagicMock:
        mock = MagicMock(spec=Path)
        for k, v in attrs.items():
            setattr(mock, k, v)
        return mock

    def test_oserror_reading_existing_wrapper(
        self, tmp_path: Path, capsys: object
    ) -> None:
        """Returns 1 when existing wrapper cannot be read."""
        fake_slopmop = tmp_path / ".slopmop"
        mock_wrapper = self._mock_wrapper()
        mock_wrapper.exists.return_value = True
        mock_wrapper.read_bytes.side_effect = OSError("permission denied")

        with (
            patch("slopmop.cli.hooks._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.hooks._WRAPPER_DEST", mock_wrapper),
        ):
            result = _deep_hooks_install(confirm=DEEP_HOOKS_CONFIRM_PHRASE)

        assert result == 1
        assert "Could not read" in capsys.readouterr().out  # type: ignore[union-attr]

    def test_oserror_writing_updated_wrapper(
        self, tmp_path: Path, capsys: object
    ) -> None:
        """Returns 1 when writing an updated wrapper fails."""
        fake_slopmop = tmp_path / ".slopmop"
        mock_wrapper = self._mock_wrapper()
        mock_wrapper.exists.return_value = True
        mock_wrapper.read_bytes.return_value = b"# old stale content"
        mock_wrapper.write_bytes.side_effect = OSError("read-only filesystem")

        with (
            patch("slopmop.cli.hooks._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.hooks._WRAPPER_DEST", mock_wrapper),
        ):
            result = _deep_hooks_install(confirm=DEEP_HOOKS_CONFIRM_PHRASE)

        assert result == 1
        assert "Could not write" in capsys.readouterr().out  # type: ignore[union-attr]

    def test_oserror_writing_new_wrapper(self, tmp_path: Path, capsys: object) -> None:
        """Returns 1 when writing a brand-new wrapper fails."""
        fake_slopmop = tmp_path / ".slopmop"
        mock_wrapper = self._mock_wrapper()
        mock_wrapper.exists.return_value = False
        mock_wrapper.write_bytes.side_effect = OSError("no space left")

        with (
            patch("slopmop.cli.hooks._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.hooks._WRAPPER_DEST", mock_wrapper),
        ):
            result = _deep_hooks_install(confirm=DEEP_HOOKS_CONFIRM_PHRASE)

        assert result == 1
        assert "Could not write" in capsys.readouterr().out  # type: ignore[union-attr]

    def test_oserror_setting_chmod(self, tmp_path: Path, capsys: object) -> None:
        """Returns 1 when chmod on wrapper fails."""
        fake_slopmop = tmp_path / ".slopmop"
        mock_wrapper = self._mock_wrapper()
        mock_wrapper.exists.return_value = False
        mock_wrapper.write_bytes.return_value = None
        mock_wrapper.stat.return_value.st_mode = 0o644
        mock_wrapper.chmod.side_effect = OSError("read-only filesystem")

        with (
            patch("slopmop.cli.hooks._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.hooks._WRAPPER_DEST", mock_wrapper),
        ):
            result = _deep_hooks_install(confirm=DEEP_HOOKS_CONFIRM_PHRASE)

        assert result == 1
        assert "Could not set executable bit" in capsys.readouterr().out  # type: ignore[union-attr]


class TestDeepHooksUninstallRcHandling:
    """Tests for RC file skip paths in _deep_hooks_uninstall."""

    def test_nonexistent_rc_file_is_skipped(self, tmp_path: Path) -> None:
        """Uninstall skips rc files that do not exist."""
        nonexistent_rc = tmp_path / "nonexistent" / ".zshrc"
        fake_wrapper = tmp_path / "nonexistent_wrapper"

        with (
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch(
                "slopmop.cli.hooks._deep_rc_candidates", return_value=[nonexistent_rc]
            ),
        ):
            result = _deep_hooks_uninstall()

        assert result == 0

    def test_rc_without_marker_is_skipped(self, tmp_path: Path) -> None:
        """Uninstall leaves rc files that do not contain the deep hook marker."""
        rc = tmp_path / ".zshrc"
        original = "# my rc file\n"
        rc.write_text(original)
        fake_wrapper = tmp_path / "nonexistent_wrapper"

        with (
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._deep_rc_candidates", return_value=[rc]),
        ):
            result = _deep_hooks_uninstall()

        assert result == 0
        assert rc.read_text() == original


class TestCmdCommitHooksDeepUninstall:
    """Tests for cmd_commit_hooks deep uninstall inside a git repo."""

    def test_deep_uninstall_in_git_repo(self, tmp_path: Path, capsys: object) -> None:
        """deep uninstall inside a git repo calls _deep_hooks_uninstall then hook uninstall."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir()

        fake_wrapper = tmp_path / "nonexistent_wrapper"
        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="uninstall",
            hook_verb="swab",
            deep=True,
            confirm="",
        )

        with (
            patch("slopmop.cli.hooks._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.hooks._deep_rc_candidates", return_value=[]),
        ):
            result = cmd_commit_hooks(args)

        assert result == 0


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
