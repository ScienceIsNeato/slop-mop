"""Tests for sm gang — command intercept alias press/discharge/status/list."""

import argparse
import importlib.resources
import os
import shlex
import stat
import subprocess
from pathlib import Path
from unittest.mock import patch

from slopmop.cli.gang import (
    _LEGACY_MARKER,
    GANG_CONFIRM_PHRASE,
    GANG_END_MARKER,
    GANG_MARKER,
    _gang_discharge,
    _gang_list,
    _gang_press,
    _gang_status,
    _generate_aliases_sh,
    _strip_marker_block,
    _validate_bash_syntax,
    _write_if_changed,
    cmd_gang,
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
        assert GANG_CONFIRM_PHRASE in content

    def test_pytest_function_present(self) -> None:
        content = _generate_aliases_sh("1.0.0").decode()
        assert "pytest()" in content
        assert "export -f pytest" in content
        assert "BASH_VERSION" in content

    def test_pytest_blocked_with_barnacle_message(self) -> None:
        content = _generate_aliases_sh("1.0.0").decode()
        assert "pytest()" in content
        assert "sm barnacle" in content
        assert "return 1" in content

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
        assert "BEGIN sm-gang" in content or "rm -f" in content


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
            f"{GANG_MARKER}\n"
            "some content\n"
            f"{GANG_END_MARKER}\n"
            "# after\n"
        )
        result = _strip_marker_block(content, GANG_MARKER, GANG_END_MARKER)
        assert GANG_MARKER not in result
        assert GANG_END_MARKER not in result
        assert "some content" not in result
        assert "# before" in result
        assert "# after" in result

    def test_no_op_when_marker_absent(self) -> None:
        content = "# just a normal rc file\n"
        result = _strip_marker_block(content, GANG_MARKER, GANG_END_MARKER)
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
        content = "# before\n" + GANG_MARKER + "\nsome content\n"
        result = _strip_marker_block(content, GANG_MARKER, GANG_END_MARKER)
        assert result == content


class TestGangPress:
    """Tests for _gang_press."""

    def test_no_confirm_returns_1(self, capsys: object) -> None:
        result = _gang_press(confirm="")
        assert result == 1
        out = capsys.readouterr().out  # type: ignore[union-attr]  # type: ignore[union-attr]
        assert "confirmation" in out.lower()  # type: ignore[union-attr]
        assert GANG_CONFIRM_PHRASE in out

    def test_wrong_confirm_blocked(self) -> None:
        result = _gang_press(confirm="sure whatever")
        assert result == 1

    def test_correct_confirm_writes_files(self, tmp_path: Path) -> None:
        """Correct phrase writes aliases.sh + git_wrapper.sh and updates rc."""
        fake_slopmop, fake_wrapper, fake_aliases, fake_rc = _make_fake_env(tmp_path)

        with (
            patch("slopmop.cli.gang._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.gang._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.gang._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.gang._get_rc_files", return_value=[fake_rc]),
        ):
            result = _gang_press(confirm=GANG_CONFIRM_PHRASE)

        assert result == 0
        assert fake_aliases.exists()
        assert fake_wrapper.exists()
        rc_text = fake_rc.read_text()
        assert GANG_MARKER in rc_text
        assert GANG_END_MARKER in rc_text
        assert 'source "$HOME/.slopmop/aliases.sh"' in rc_text
        assert 'alias git="$HOME/.slopmop/bin/git_wrapper.sh"' in rc_text
        assert "# existing rc content" in rc_text  # original preserved

    def test_git_wrapper_is_executable(self, tmp_path: Path) -> None:
        """Pressed git_wrapper.sh has execute bits set."""
        fake_slopmop, fake_wrapper, fake_aliases, fake_rc = _make_fake_env(tmp_path)

        with (
            patch("slopmop.cli.gang._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.gang._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.gang._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.gang._get_rc_files", return_value=[fake_rc]),
        ):
            _gang_press(confirm=GANG_CONFIRM_PHRASE)

        assert fake_wrapper.stat().st_mode & stat.S_IXUSR

    def test_idempotent_aliases_no_rewrites(
        self, tmp_path: Path, capsys: object
    ) -> None:
        """Second press with identical content skips writes and rc insertion."""
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
        fake_rc.write_text(f"# before\n{GANG_MARKER}\n...\n{GANG_END_MARKER}\n")

        with (
            patch("slopmop.cli.gang._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.gang._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.gang._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.gang._get_rc_files", return_value=[fake_rc]),
        ):
            result = _gang_press(confirm=GANG_CONFIRM_PHRASE)

        assert result == 0
        out = capsys.readouterr().out  # type: ignore[union-attr]  # type: ignore[union-attr]
        assert "up to date" in out
        assert "already present" in out

    def test_rc_not_duplicated_on_repeat(self, tmp_path: Path) -> None:
        """The gang rc block is only appended once even after repeated presses."""
        fake_slopmop, fake_wrapper, fake_aliases, fake_rc = _make_fake_env(tmp_path)

        with (
            patch("slopmop.cli.gang._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.gang._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.gang._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.gang._get_rc_files", return_value=[fake_rc]),
        ):
            _gang_press(confirm=GANG_CONFIRM_PHRASE)
            _gang_press(confirm=GANG_CONFIRM_PHRASE)

        rc_text = fake_rc.read_text()
        assert rc_text.count(GANG_MARKER) == 1


# ── _gang_discharge ───────────────────────────────────────────────────────────


class TestGangDischarge:
    """Tests for _gang_discharge."""

    def test_removes_aliases_and_wrapper(self, tmp_path: Path) -> None:
        _, fake_wrapper, fake_aliases, _ = _make_fake_env(tmp_path)
        fake_wrapper.parent.mkdir(parents=True, exist_ok=True)
        fake_wrapper.write_bytes(b"#!/bin/bash\n")
        fake_aliases.parent.mkdir(parents=True, exist_ok=True)
        fake_aliases.write_bytes(b"# aliases\n")

        with (
            patch("slopmop.cli.gang._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.gang._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.gang._rc_candidates", return_value=[]),
        ):
            result = _gang_discharge()

        assert result == 0
        assert not fake_aliases.exists()
        assert not fake_wrapper.exists()

    def test_strips_gang_block_from_rc(self, tmp_path: Path) -> None:
        """Discharge removes the GANG_MARKER block from rc files."""
        _, fake_wrapper, fake_aliases, fake_rc = _make_fake_env(tmp_path)
        fake_rc.write_text(
            "# before\n"
            f"{GANG_MARKER}\n"
            'source "$HOME/.slopmop/aliases.sh"\n'
            f"{GANG_END_MARKER}\n"
            "# after\n"
        )

        with (
            patch("slopmop.cli.gang._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.gang._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.gang._rc_candidates", return_value=[fake_rc]),
        ):
            result = _gang_discharge()

        assert result == 0
        rc_text = fake_rc.read_text()
        assert GANG_MARKER not in rc_text
        assert "# before" in rc_text
        assert "# after" in rc_text

    def test_strips_legacy_deep_hook_block(self, tmp_path: Path) -> None:
        """Discharge also strips the old deep-hooks marker block for migration."""
        _, fake_wrapper, fake_aliases, fake_rc = _make_fake_env(tmp_path)
        fake_rc.write_text(
            f"{_LEGACY_MARKER}\n"
            'alias git="$HOME/.slopmop/bin/git_wrapper.sh"\n'
            "# END SLOP-MOP DEEP\n"
        )

        with (
            patch("slopmop.cli.gang._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.gang._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.gang._rc_candidates", return_value=[fake_rc]),
        ):
            result = _gang_discharge()

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
            patch("slopmop.cli.gang._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.gang._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.gang._rc_candidates", return_value=[]),
        ):
            result = _gang_discharge()

        assert result == 0
        out = capsys.readouterr().out  # type: ignore[union-attr]  # type: ignore[union-attr]
        assert "not found" in out

    def test_discharge_leaves_rc_byte_identical(self, tmp_path: Path) -> None:
        """Press then discharge leaves the rc file byte-for-byte identical to the original."""
        fake_slopmop, fake_wrapper, fake_aliases, fake_rc = _make_fake_env(tmp_path)
        original = fake_rc.read_bytes()

        with (
            patch("slopmop.cli.gang._SLOPMOP_HOME", fake_slopmop),
            patch("slopmop.cli.gang._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.gang._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.gang._get_rc_files", return_value=[fake_rc]),
            patch("slopmop.cli.gang._rc_candidates", return_value=[fake_rc]),
        ):
            _gang_press(confirm=GANG_CONFIRM_PHRASE)
            _gang_discharge()

        assert fake_rc.read_bytes() == original


# ── _gang_status ──────────────────────────────────────────────────────────────


class TestGangStatus:
    """Tests for _gang_status output."""

    def test_shows_installed_when_files_present(
        self, tmp_path: Path, capsys: object
    ) -> None:
        fake_aliases = tmp_path / "aliases.sh"
        fake_aliases.write_bytes(b"# aliases\n")
        fake_wrapper = tmp_path / "git_wrapper.sh"
        fake_wrapper.write_bytes(b"#!/bin/bash\n")

        with (
            patch("slopmop.cli.gang._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.gang._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.gang._rc_candidates", return_value=[]),
        ):
            result = _gang_status()

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
            patch("slopmop.cli.gang._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.gang._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.gang._rc_candidates", return_value=[]),
        ):
            result = _gang_status()

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
            patch("slopmop.cli.gang._ALIASES_DEST", fake_aliases),
            patch("slopmop.cli.gang._WRAPPER_DEST", fake_wrapper),
            patch("slopmop.cli.gang._rc_candidates", return_value=[fake_rc]),
        ):
            _gang_status()

        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "Legacy" in out or "legacy" in out


# ── _gang_list ────────────────────────────────────────────────────────────────


class TestGangList:
    """Tests for _gang_list output."""

    def test_prints_summary(self, capsys: object) -> None:
        result = _gang_list()
        assert result == 0
        out = capsys.readouterr().out  # type: ignore[union-attr]
        assert "intercept" in out

    def test_no_forbidden_commands_in_output(self, capsys: object) -> None:
        _gang_list()
        out = capsys.readouterr().out  # type: ignore[union-attr]
        for entry in COMMAND_MAPPING:
            assert (
                entry.forbidden not in out
            ), f"{entry.forbidden} leaked into list output"


# ── cmd_gang dispatcher ───────────────────────────────────────────────────────


class TestCmdGang:
    """Tests for the cmd_gang dispatcher."""

    def test_dispatch_status(self) -> None:
        args = argparse.Namespace(gang_action="status")
        with (
            patch("slopmop.cli.gang._ALIASES_DEST", Path("/nonexistent/aliases")),
            patch("slopmop.cli.gang._WRAPPER_DEST", Path("/nonexistent/wrapper")),
            patch("slopmop.cli.gang._rc_candidates", return_value=[]),
        ):
            result = cmd_gang(args)
        assert result == 0

    def test_dispatch_list(self) -> None:
        args = argparse.Namespace(gang_action="list")
        result = cmd_gang(args)
        assert result == 0

    def test_dispatch_press_no_confirm(self) -> None:
        args = argparse.Namespace(gang_action="press", confirm="")
        result = cmd_gang(args)
        assert result == 1

    def test_dispatch_discharge(self) -> None:
        args = argparse.Namespace(gang_action="discharge")
        with (
            patch("slopmop.cli.gang._ALIASES_DEST", Path("/nonexistent/aliases")),
            patch("slopmop.cli.gang._WRAPPER_DEST", Path("/nonexistent/wrapper")),
            patch("slopmop.cli.gang._rc_candidates", return_value=[]),
        ):
            result = cmd_gang(args)
        assert result == 0

    def test_dispatch_unknown_action(self) -> None:
        args = argparse.Namespace(gang_action="explode")
        result = cmd_gang(args)
        assert result == 1

    def test_default_action_is_status(self) -> None:
        """Missing gang_action defaults to status."""
        args = argparse.Namespace(gang_action=None)
        with (
            patch("slopmop.cli.gang._ALIASES_DEST", Path("/nonexistent/aliases")),
            patch("slopmop.cli.gang._WRAPPER_DEST", Path("/nonexistent/wrapper")),
            patch("slopmop.cli.gang._rc_candidates", return_value=[]),
        ):
            result = cmd_gang(args)
        assert result == 0


# ── Integration: real bash subprocess ─────────────────────────────────────────


class TestIntegrationAliasesSh:
    """Source the generated aliases.sh in a real bash subprocess and verify intercept behaviour."""

    @staticmethod
    def _make_aliases(tmp_path: Path) -> Path:
        from slopmop import __version__

        p = tmp_path / "aliases.sh"
        p.write_bytes(_generate_aliases_sh(__version__))
        return p

    @staticmethod
    def _make_fake_bin(tmp_path: Path, tools: tuple[str, ...]) -> Path:
        d = tmp_path / "fakebin"
        d.mkdir(exist_ok=True)
        for name in tools:
            exe = d / name
            exe.write_text(f"#!/bin/bash\necho 'fake-{name}:' \"$@\"\n")
            exe.chmod(0o755)
        return d

    @staticmethod
    def _bash(
        aliases: Path, path_prefix: Path, cmd: str
    ) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PATH": f"{path_prefix}:{os.environ['PATH']}"}
        return subprocess.run(
            ["bash", "-c", f"source {shlex.quote(str(aliases))} && {cmd}"],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_generated_script_passes_bash_syntax_check(self, tmp_path: Path) -> None:
        aliases = self._make_aliases(tmp_path)
        result = subprocess.run(["bash", "-n", str(aliases)], capture_output=True)
        assert result.returncode == 0, result.stderr.decode()

    def test_validate_bash_syntax_helper_passes(self, tmp_path: Path) -> None:
        aliases = self._make_aliases(tmp_path)
        ok, err = _validate_bash_syntax(aliases.read_bytes())
        assert ok, f"bash syntax check failed: {err}"

    def test_pytest_intercept_fires(self, tmp_path: Path) -> None:
        aliases = self._make_aliases(tmp_path)
        fake_bin = self._make_fake_bin(tmp_path, ("sm", "pytest"))
        result = self._bash(aliases, fake_bin, "pytest")
        assert "[slop-mop]" in result.stderr
        assert "barnacle" in result.stderr
        assert result.returncode == 1

    def test_gh_run_list_blocked(self, tmp_path: Path) -> None:
        aliases = self._make_aliases(tmp_path)
        fake_bin = self._make_fake_bin(tmp_path, ("sm", "gh"))
        result = self._bash(aliases, fake_bin, "gh run list")
        assert "[slop-mop]" in result.stderr
        assert result.returncode == 1

    def test_gh_unknown_subcommand_passes_through(self, tmp_path: Path) -> None:
        aliases = self._make_aliases(tmp_path)
        fake_bin = self._make_fake_bin(tmp_path, ("sm", "gh"))
        result = self._bash(aliases, fake_bin, "gh repo clone owner/repo")
        assert "[slop-mop]" not in result.stderr
        assert "fake-gh" in result.stdout

    def test_sm_not_found_falls_through_to_real_command(self, tmp_path: Path) -> None:
        """When sm is absent from PATH, intercepts fall through to the real command."""
        import shutil

        aliases = self._make_aliases(tmp_path)
        no_sm_bin = self._make_fake_bin(tmp_path, ("pytest",))
        bash = shutil.which("bash") or "/bin/bash"
        result = subprocess.run(
            [bash, "-c", f"source {shlex.quote(str(aliases))} && pytest --version"],
            capture_output=True,
            text=True,
            env={**os.environ, "PATH": str(no_sm_bin)},
        )
        assert "[slop-mop]" not in result.stderr
        assert "fake-pytest" in result.stdout
