"""Tests for deep hooks — system-level git wrapper install/uninstall."""

import argparse
import importlib.resources
import stat
from unittest.mock import patch

from slopmop.cli.hooks import (
    DEEP_HOOK_MARKER,
    DEEP_HOOKS_CONFIRM_PHRASE,
    _deep_hooks_install,
    _deep_hooks_uninstall,
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
