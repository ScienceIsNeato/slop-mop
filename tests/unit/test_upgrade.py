"""Tests for the upgrade CLI command."""

import argparse
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from slopmop.cli.upgrade import (
    UpgradeError,
    _backup_upgrade_state,
    _detect_install_type,
    _upgrade_command,
    cmd_upgrade,
)


class TestDetectInstallType:
    def test_detects_pipx_from_executable_path(self):
        detected = _detect_install_type(
            executable="/Users/me/.local/pipx/venvs/slopmop/bin/python",
            prefix="/Users/me/.local/pipx/venvs/slopmop",
            base_prefix="/usr/local/Cellar/python/3.13",
            virtual_env=None,
            direct_url=None,
        )
        assert detected == "pipx"

    def test_detects_active_virtualenv(self):
        detected = _detect_install_type(
            executable="/tmp/project/.venv/bin/python",
            prefix="/tmp/project/.venv",
            base_prefix="/opt/homebrew/Cellar/python/3.13",
            virtual_env="/tmp/project/.venv",
            direct_url=None,
        )
        assert detected == "venv"

    def test_rejects_editable_install(self):
        try:
            _detect_install_type(
                executable="/tmp/project/.venv/bin/python",
                prefix="/tmp/project/.venv",
                base_prefix="/opt/homebrew/Cellar/python/3.13",
                virtual_env="/tmp/project/.venv",
                direct_url={"dir_info": {"editable": True}},
            )
        except RuntimeError as exc:
            assert "editable/source-checkout installs" in str(exc)
        else:
            raise AssertionError("expected editable installs to be rejected")


class TestBackupUpgradeState:
    def test_backup_copies_config_and_state_files(self, tmp_path: Path):
        config = tmp_path / ".sb_config.json"
        config.write_text("{}")
        state_dir = tmp_path / ".slopmop"
        state_dir.mkdir()
        (state_dir / "timings.json").write_text("{}")

        backup_dir = _backup_upgrade_state(
            tmp_path,
            from_version="0.9.0",
            target_version="0.9.1",
            install_type="venv",
        )

        assert (backup_dir / ".sb_config.json").exists()
        assert (backup_dir / "timings.json").exists()
        manifest = json.loads((backup_dir / "manifest.json").read_text())
        assert manifest["from_version"] == "0.9.0"
        assert manifest["target_version"] == "0.9.1"
        assert manifest["install_type"] == "venv"


class TestUpgradeCommand:
    @patch("slopmop.cli.upgrade._print_check_plan")
    @patch("slopmop.cli.upgrade._validate_target_version")
    @patch("slopmop.cli.upgrade._resolve_target_version", return_value="0.9.1")
    @patch("slopmop.cli.upgrade._detect_install_type", return_value="venv")
    @patch("slopmop.cli.upgrade._installed_version", return_value="0.9.0")
    def test_check_mode_does_not_mutate(
        self,
        _mock_installed,
        _mock_detect,
        _mock_target,
        _mock_validate_version,
        mock_print_plan,
        tmp_path,
    ):
        args = argparse.Namespace(
            project_root=str(tmp_path),
            check=True,
            to_version=None,
            verbose=False,
        )
        assert cmd_upgrade(args) == 0
        mock_print_plan.assert_called_once()

    @patch("slopmop.cli.upgrade._validate_upgraded_install")
    @patch("slopmop.cli.upgrade.run_upgrade_migrations", return_value=[])
    @patch("slopmop.cli.upgrade._run_upgrade_install")
    @patch("slopmop.cli.upgrade._backup_upgrade_state")
    @patch("slopmop.cli.upgrade._validate_target_version")
    @patch("slopmop.cli.upgrade._resolve_target_version", return_value="0.9.1")
    @patch("slopmop.cli.upgrade._detect_install_type", return_value="venv")
    @patch("slopmop.cli.upgrade._installed_version", side_effect=["0.9.0", "0.9.1"])
    def test_upgrade_runs_backup_install_migrations_and_validation(
        self,
        _mock_installed,
        _mock_detect,
        _mock_target,
        _mock_validate_version,
        mock_backup,
        mock_run_install,
        mock_run_migrations,
        mock_validate,
        tmp_path,
        capsys,
    ):
        mock_backup.return_value = tmp_path / ".slopmop" / "backups" / "upgrade_x"
        mock_validate.return_value = subprocess.CompletedProcess(
            args=["python", "-m", "slopmop", "scour"],
            returncode=0,
            stdout="",
            stderr="",
        )
        args = argparse.Namespace(
            project_root=str(tmp_path),
            check=False,
            to_version=None,
            verbose=False,
        )

        assert cmd_upgrade(args) == 0
        mock_backup.assert_called_once()
        mock_run_install.assert_called_once_with("venv", "0.9.1")
        mock_run_migrations.assert_called_once()
        mock_validate.assert_called_once()
        out = capsys.readouterr().out
        assert "Upgraded slopmop: 0.9.0 -> 0.9.1" in out

    @patch("slopmop.cli.upgrade._validate_target_version")
    @patch("slopmop.cli.upgrade._resolve_target_version", return_value="0.9.1")
    @patch(
        "slopmop.cli.upgrade._detect_install_type",
        side_effect=UpgradeError("bad install"),
    )
    @patch("slopmop.cli.upgrade._installed_version", return_value="0.9.0")
    def test_upgrade_fails_for_unsupported_install(
        self,
        _mock_installed,
        _mock_detect,
        _mock_target,
        _mock_validate_version,
        tmp_path,
        capsys,
    ):
        args = argparse.Namespace(
            project_root=str(tmp_path),
            check=False,
            to_version=None,
            verbose=False,
        )

        assert cmd_upgrade(args) == 1
        err = capsys.readouterr().err
        assert "bad install" in err


class TestUpgradeCommandLine:
    def test_upgrade_command_for_venv_uses_python_m_pip(self):
        command = _upgrade_command("venv", "0.9.1")
        assert command[:3] == [__import__("sys").executable, "-m", "pip"]
        assert command[-1] == "slopmop==0.9.1"

    @patch("slopmop.cli.upgrade.shutil.which", return_value="/opt/homebrew/bin/pipx")
    def test_upgrade_command_for_pipx_uses_force_install(self, _mock_which):
        command = _upgrade_command("pipx", "0.9.1")
        assert command == [
            "/opt/homebrew/bin/pipx",
            "install",
            "--force",
            "slopmop==0.9.1",
        ]
