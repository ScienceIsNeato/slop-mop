"""Tests for sm mutinize — command intercept alias install/uninstall/status/list."""

import argparse
import importlib.resources
import stat
from pathlib import Path
from unittest.mock import patch

from slopmop.cli.mutinize import (
    _LEGACY_MARKER,
    MUTINIZE_CONFIRM_PHRASE,
    MUTINIZE_END_MARKER,
    MUTINIZE_MARKER,
    _generate_aliases_sh,
    _mutinize_install,
    _mutinize_list,
    _mutinize_status,
    _mutinize_uninstall,
    _strip_marker_block,
    _write_if_changed,
    cmd_mutinize,
)
from slopmop.data.command_mapping import COMMAND_MAPPING

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fake_env(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Return (slopmop_home, wrapper_dest, aliases_dest, fake_rc)."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_slopmop = fake_home / ".slopmop"
    fake_wrapper = fake_slopmop / "bin" / "git_wrapper.sh"
    fake_aliases = fake_slopmop / "aliases.sh"
    fake_rc = fake_home / ".zshrc"
    fake_rc.write_text("# existing rc content\n")
    return fake_slopmop, fake_wrapper, fake_aliases, fake_rc


# ── command_mapping data integrity ───────────────────────────────────────────


class TestCommandMapping:
    """Sanity checks on the COMMAND_MAPPING data."""

    def test_all_entries_have_required_fields(self) -> None:
        for entry in COMMAND_MAPPING:
            assert entry.forbidden, f"empty forbidden in {entry}"
            assert entry.category, f"empty category in {entry}"
            assert entry.intercept_type in (
                "function",
                "subcommand",
                "npx",
            ), f"unknown intercept_type: {entry.intercept_type}"

    def test_function_entries_have_sm_command(self) -> None:
        for entry in COMMAND_MAPPING:
            if entry.intercept_type == "function":
                assert entry.sm_command, f"function entry missing sm_command: {entry}"

    def test_subcommand_entries_have_wrapper_and_subcommands(self) -> None:
        for entry in COMMAND_MAPPING:
            if entry.intercept_type in ("subcommand", "npx"):
                assert entry.wrapper_command, f"missing wrapper_command: {entry}"
                assert entry.subcommands, f"missing subcommands: {entry}"

    def test_block_only_entries_have_suggestion(self) -> None:
        for entry in COMMAND_MAPPING:
            if not entry.redirect and not entry.sm_command:
                assert entry.suggestion, f"block-only entry missing suggestion: {entry}"

    def test_flag_trigger_entries_paired_with_plain(self) -> None:
        """For every flagged variant there must be a plain (catch-all) entry for the same command."""
        flagged_cmds = {
            e.forbidden.split()[0]
            for e in COMMAND_MAPPING
            if e.intercept_type == "function" and e.flag_trigger
        }
        plain_cmds = {
            e.forbidden.split()[0]
            for e in COMMAND_MAPPING
            if e.intercept_type == "function" and not e.flag_trigger
        }
        for cmd in flagged_cmds:
            assert cmd in plain_cmds, f"no plain catch-all for flagged command: {cmd}"


# ── alias generation ──────────────────────────────────────────────────────────


class TestGenerateAliasesSh:
    """Tests for _generate_aliases_sh output correctness."""

    def test_returns_bytes(self) -> None:
        content = _generate_aliases_sh("1.2.3")
        assert isinstance(content, bytes)

    def test_shebang_present(self) -> None:
        content = _generate_aliases_sh("0.0.1").decode()
        assert content.startswith("#!/usr/bin/env bash")

    def test_version_in_header(self) -> None:
        content = _generate_aliases_sh("9.8.7").decode()
        assert "9.8.7" in content

    def test_confirm_phrase_in_header(self) -> None:
        content = _generate_aliases_sh("1.0.0").decode()
        assert MUTINIZE_CONFIRM_PHRASE in content

    def test_pytest_function_present(self) -> None:
        content = _generate_aliases_sh("1.0.0").decode()
        assert "pytest()" in content
        assert "export -f pytest" in content
        assert "BASH_VERSION" in content

    def test_pytest_cov_variant_routed_to_scour(self) -> None:
        content = _generate_aliases_sh("1.0.0").decode()
        assert "--cov" in content
        assert "sm scour" in content

    def test_gh_wrapper_present(self) -> None:
        content = _generate_aliases_sh("1.0.0").decode()
        assert "gh()" in content
        assert "export -f gh" in content

    def test_gh_run_case_arm_present(self) -> None:
        content = _generate_aliases_sh("1.0.0").decode()
        assert "run list" in content or "run" in content
        assert "return 1" in content

    def test_npx_wrapper_present(self) -> None:
        content = _generate_aliases_sh("1.0.0").decode()
        assert "npx()" in content
        assert "export -f npx" in content
        assert "knip" in content

    def test_all_function_type_commands_present(self) -> None:
        content = _generate_aliases_sh("1.0.0").decode()
        fn_cmds = {
            e.forbidden.split()[0]
            for e in COMMAND_MAPPING
            if e.intercept_type == "function"
        }
        for cmd in fn_cmds:
            assert f"{cmd}()" in content, f"missing function wrapper for {cmd}"
            assert f"export -f {cmd}" in content

    def test_bypass_hint_in_header(self) -> None:
        content = _generate_aliases_sh("1.0.0").decode()
        assert "command <tool>" in content or "command " in content


# ── _write_if_changed ─────────────────────────────────────────────────────────


class TestWriteIfChanged:
    """Tests for the SHA256-guarded write helper."""

    def test_writes_new_file(self, tmp_path: Path) -> None:
        dest = tmp_path / "file.txt"
        written, msg = _write_if_changed(dest, b"hello")
        assert written is True
        assert dest.read_bytes() == b"hello"
        assert "Written" in msg

    def test_skips_identical_content(self, tmp_path: Path) -> None:
        dest = tmp_path / "file.txt"
        dest.write_bytes(b"hello")
        written, msg = _write_if_changed(dest, b"hello")
        assert written is False
        assert "up to date" in msg

    def test_overwrites_changed_content(self, tmp_path: Path) -> None:
        dest = tmp_path / "file.txt"
        dest.write_bytes(b"old")
        written, _ = _write_if_changed(dest, b"new")
        assert written is True
        assert dest.read_bytes() == b"new"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        dest = tmp_path / "deep" / "nested" / "file.txt"
        written, _ = _write_if_changed(dest, b"content")
        assert written is True
        assert dest.exists()


# ── _strip_marker_block ───────────────────────────────────────────────────────


class TestStripMarkerBlock:
    """Tests for the rc-file marker block removal helper."""

    def test_removes_block_preserves_surrounding(self) -> None:
        content = (
            "# before\n"
            f"{MUTINIZE_MARKER}\n"
            "some content\n"
            f"{MUTINIZE_END_MARKER}\n"
            "# after\n"
        )
        result = _strip_marker_block(content, MUTINIZE_MARKER, MUTINIZE_END_MARKER)
        assert MUTINIZE_MARKER not in result
        assert MUTINIZE_END_MARKER not in result
        assert "some content" not in result
        assert "# before" in result
        assert "# after" in result

    def test_no_op_when_marker_absent(self) -> None:
        content = "# just a normal rc file\n"
        result = _strip_marker_block(content, MUTINIZE_MARKER, MUTINIZE_END_MARKER)
        assert result == content

    def test_strips_legacy_marker(self) -> None:
        content = (
            f"{_LEGACY_MARKER}\n"
            'alias git="$HOME/.slopmop/bin/git_wrapper.sh"\n'
            "# END SLOP-MOP DEEP\n"
        )
        result = _strip_marker_block(content, _LEGACY_MARKER, "# END SLOP-MOP DEEP")
        assert _LEGACY_MARKER not in result
        assert "alias git" not in result

    def test_orphaned_start_marker_returns_original(self) -> None:
        """Content after an orphaned start marker is NOT silently dropped."""
        content = "# before\n" + MUTINIZE_MARKER + "\nsome content\n"
        result = _strip_marker_block(content, MUTINIZE_MARKER, MUTINIZE_END_MARKER)
        assert result == content


class TestMutinizeInstall:
    """Tests for _mutinize_install."""

    def test_no_confirm_returns_1(self, capsys: object) -> None:
        result = _mutinize_install(confirm="")
        assert result == 1
        out = capsys.readouterr().out  # type: ignore[union-attr]  # type: ignore[union-attr]
        assert "confirmation" in out.lower()  # type: ignore[union-attr]
        assert MUTINIZE_CONFIRM_PHRASE in out

    def test_wrong_confirm_blocked(self) -> None:
        result = _mutinize_install(confirm="sure whatever")
        assert result == 1

    def test_correct_confirm_writes_files(self, tmp_path: Path) -> None:
        """Correct phrase writes aliases.sh + git_wrapper.sh and updates rc."""
        fake_slopmop, fake_wrapper, fake_aliases, fake_rc = _make_fake_env(tmp_path)

        with (
            patch("slopmop.cli.mutinize._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.mutinize._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.mutinize._get_rc_files", return_value=[fake_rc]),
        ):
            result = _mutinize_install(confirm=MUTINIZE_CONFIRM_PHRASE)

        assert result == 0
        assert fake_aliases.exists()
        assert fake_wrapper.exists()
        rc_text = fake_rc.read_text()
        assert MUTINIZE_MARKER in rc_text
        assert MUTINIZE_END_MARKER in rc_text
        assert 'source "$HOME/.slopmop/aliases.sh"' in rc_text
        assert 'alias git="$HOME/.slopmop/bin/git_wrapper.sh"' in rc_text
        assert "# existing rc content" in rc_text  # original preserved

    def test_git_wrapper_is_executable(self, tmp_path: Path) -> None:
        """Installed git_wrapper.sh has execute bits set."""
        fake_slopmop, fake_wrapper, fake_aliases, fake_rc = _make_fake_env(tmp_path)

        with (
            patch("slopmop.cli.mutinize._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.mutinize._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.mutinize._get_rc_files", return_value=[fake_rc]),
        ):
            _mutinize_install(confirm=MUTINIZE_CONFIRM_PHRASE)

        assert fake_wrapper.stat().st_mode & stat.S_IXUSR

    def test_idempotent_aliases_no_rewrites(
        self, tmp_path: Path, capsys: object
    ) -> None:
        """Second install with identical content skips writes and rc insertion."""
        from slopmop import __version__

        fake_slopmop, fake_wrapper, fake_aliases, fake_rc = _make_fake_env(tmp_path)
        # Pre-populate with the exact content that would be generated
        fake_aliases.parent.mkdir(parents=True, exist_ok=True)
        fake_aliases.write_bytes(_generate_aliases_sh(__version__))
        real_wrapper_bytes = (
            importlib.resources.files("slopmop.data")
            .joinpath("git_wrapper.sh")
            .read_bytes()
        )
        fake_wrapper.parent.mkdir(parents=True, exist_ok=True)
        fake_wrapper.write_bytes(real_wrapper_bytes)
        fake_wrapper.chmod(0o755)
        # RC file already has the marker
        fake_rc.write_text(f"# before\n{MUTINIZE_MARKER}\n...\n{MUTINIZE_END_MARKER}\n")

        with (
            patch("slopmop.cli.mutinize._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.mutinize._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.mutinize._get_rc_files", return_value=[fake_rc]),
        ):
            result = _mutinize_install(confirm=MUTINIZE_CONFIRM_PHRASE)

        assert result == 0
        out = capsys.readouterr().out  # type: ignore[union-attr]  # type: ignore[union-attr]
        assert "up to date" in out
        assert "already present" in out

    def test_rc_not_duplicated_on_repeat(self, tmp_path: Path) -> None:
        """The mutinize rc block is only appended once even after repeated installs."""
        fake_slopmop, fake_wrapper, fake_aliases, fake_rc = _make_fake_env(tmp_path)

        with (
            patch("slopmop.cli.mutinize._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.mutinize._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.mutinize._get_rc_files", return_value=[fake_rc]),
        ):
            _mutinize_install(confirm=MUTINIZE_CONFIRM_PHRASE)
            _mutinize_install(confirm=MUTINIZE_CONFIRM_PHRASE)

        rc_text = fake_rc.read_text()
        assert rc_text.count(MUTINIZE_MARKER) == 1


# ── _mutinize_uninstall ───────────────────────────────────────────────────────


class TestMutinizeUninstall:
    """Tests for _mutinize_uninstall."""

    def test_removes_aliases_and_wrapper(self, tmp_path: Path) -> None:
        _, fake_wrapper, fake_aliases, _ = _make_fake_env(tmp_path)
        fake_wrapper.parent.mkdir(parents=True, exist_ok=True)
        fake_wrapper.write_bytes(b"#!/bin/bash\n")
        fake_aliases.parent.mkdir(parents=True, exist_ok=True)
        fake_aliases.write_bytes(b"# aliases\n")

        with (
            patch("slopmop.cli.mutinize._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.mutinize._rc_candidates", return_value=[]),
        ):
            result = _mutinize_uninstall()

        assert result == 0
        assert not fake_aliases.exists()
        assert not fake_wrapper.exists()

    def test_strips_mutinize_block_from_rc(self, tmp_path: Path) -> None:
        """Uninstall removes the MUTINIZE_MARKER block from rc files."""
        _, fake_wrapper, fake_aliases, fake_rc = _make_fake_env(tmp_path)
        fake_rc.write_text(
            "# before\n"
            f"{MUTINIZE_MARKER}\n"
            'source "$HOME/.slopmop/aliases.sh"\n'
            f"{MUTINIZE_END_MARKER}\n"
            "# after\n"
        )

        with (
            patch("slopmop.cli.mutinize._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.mutinize._rc_candidates", return_value=[fake_rc]),
        ):
            result = _mutinize_uninstall()

        assert result == 0
        rc_text = fake_rc.read_text()
        assert MUTINIZE_MARKER not in rc_text
        assert "# before" in rc_text
        assert "# after" in rc_text

    def test_strips_legacy_deep_hook_block(self, tmp_path: Path) -> None:
        """Uninstall also strips the old deep-hooks marker block for migration."""
        _, fake_wrapper, fake_aliases, fake_rc = _make_fake_env(tmp_path)
        fake_rc.write_text(
            f"{_LEGACY_MARKER}\n"
            'alias git="$HOME/.slopmop/bin/git_wrapper.sh"\n'
            "# END SLOP-MOP DEEP\n"
        )

        with (
            patch("slopmop.cli.mutinize._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.mutinize._rc_candidates", return_value=[fake_rc]),
        ):
            result = _mutinize_uninstall()

        assert result == 0
        rc_text = fake_rc.read_text()
        assert _LEGACY_MARKER not in rc_text
        assert "alias git" not in rc_text

    def test_clean_machine_no_files_exits_cleanly(
        self, tmp_path: Path, capsys: object
    ) -> None:
        fake_aliases = tmp_path / "nonexistent_aliases.sh"
        fake_wrapper = tmp_path / "nonexistent_wrapper.sh"

        with (
            patch("slopmop.cli.mutinize._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.mutinize._rc_candidates", return_value=[]),
        ):
            result = _mutinize_uninstall()

        assert result == 0
        out = capsys.readouterr().out  # type: ignore[union-attr]  # type: ignore[union-attr]
        assert "not found" in out


# ── _mutinize_status ──────────────────────────────────────────────────────────


class TestMutinizeStatus:
    """Tests for _mutinize_status output."""

    def test_shows_installed_when_files_present(
        self, tmp_path: Path, capsys: object
    ) -> None:
        fake_aliases = tmp_path / "aliases.sh"
        fake_aliases.write_bytes(b"# aliases\n")
        fake_wrapper = tmp_path / "git_wrapper.sh"
        fake_wrapper.write_bytes(b"#!/bin/bash\n")

        with (
            patch("slopmop.cli.mutinize._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.mutinize._rc_candidates", return_value=[]),
        ):
            result = _mutinize_status()

        assert result == 0
        out = capsys.readouterr().out  # type: ignore[union-attr]  # type: ignore[union-attr]
        assert "aliases.sh installed" in out
        assert "git_wrapper.sh installed" in out

    def test_shows_not_installed_when_missing(
        self, tmp_path: Path, capsys: object
    ) -> None:
        fake_aliases = tmp_path / "missing_aliases.sh"
        fake_wrapper = tmp_path / "missing_wrapper.sh"

        with (
            patch("slopmop.cli.mutinize._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.mutinize._rc_candidates", return_value=[]),
        ):
            result = _mutinize_status()

        assert result == 0
        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "not installed" in out

    def test_detects_legacy_marker(self, tmp_path: Path, capsys: object) -> None:
        """Status warns when old deep-hooks block is still in an rc file."""
        fake_rc = tmp_path / ".zshrc"
        fake_rc.write_text(f"{_LEGACY_MARKER}\nalias git=...\n# END SLOP-MOP DEEP\n")
        fake_aliases = tmp_path / "missing_aliases.sh"
        fake_wrapper = tmp_path / "missing_wrapper.sh"

        with (
            patch("slopmop.cli.mutinize._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.mutinize._rc_candidates", return_value=[fake_rc]),
        ):
            _mutinize_status()

        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "Legacy" in out or "legacy" in out


# ── _mutinize_list ────────────────────────────────────────────────────────────


class TestMutinizeList:
    """Tests for _mutinize_list output."""

    def test_prints_all_categories(self, capsys: object) -> None:
        result = _mutinize_list()
        assert result == 0
        out = capsys.readouterr().out  # type: ignore[union-attr]
        categories = {e.category for e in COMMAND_MAPPING}
        for cat in categories:
            assert cat in out

    def test_prints_bypass_hint(self, capsys: object) -> None:
        _mutinize_list()
        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "command" in out  # "command <tool> <args>"

    def test_all_forbidden_commands_listed(self, capsys: object) -> None:
        _mutinize_list()
        out = capsys.readouterr().out  # type: ignore[union-attr]
        for entry in COMMAND_MAPPING:
            assert entry.forbidden in out, f"missing {entry.forbidden} in list output"


# ── cmd_mutinize dispatcher ───────────────────────────────────────────────────


class TestCmdMutinize:
    """Tests for the cmd_mutinize dispatcher."""

    def test_dispatch_status(self) -> None:
        args = argparse.Namespace(mutinize_action="status")
        with (
            patch("slopmop.cli.mutinize._ALIASES_DEST", Path("/nonexistent/aliases")),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", Path("/nonexistent/wrapper")),
            patch("slopmop.cli.mutinize._rc_candidates", return_value=[]),
        ):
            result = cmd_mutinize(args)
        assert result == 0

    def test_dispatch_list(self) -> None:
        args = argparse.Namespace(mutinize_action="list")
        result = cmd_mutinize(args)
        assert result == 0

    def test_dispatch_install_no_confirm(self) -> None:
        args = argparse.Namespace(mutinize_action="install", confirm="")
        result = cmd_mutinize(args)
        assert result == 1

    def test_dispatch_unknown_action(self) -> None:
        args = argparse.Namespace(mutinize_action="explode")
        result = cmd_mutinize(args)
        assert result == 1

    def test_default_action_is_status(self) -> None:
        """Missing mutinize_action defaults to status."""
        args = argparse.Namespace(mutinize_action=None)
        with (
            patch("slopmop.cli.mutinize._ALIASES_DEST", Path("/nonexistent/aliases")),
            patch("slopmop.cli.mutinize._WRAPPER_DEST", Path("/nonexistent/wrapper")),
            patch("slopmop.cli.mutinize._rc_candidates", return_value=[]),
        ):
            result = cmd_mutinize(args)
        assert result == 0
