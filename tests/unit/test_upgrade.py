"""Tests for the upgrade CLI command."""

import argparse
import json
import subprocess
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slopmop import MissingDependencyError
from slopmop.cli.upgrade import (
    UpgradeError,
    _backup_upgrade_state,
    _detect_install_type,
    _distribution_direct_url,
    _fetch_latest_pypi_version,
    _installed_version_fresh,
    _is_editable_install,
    _require_packaging,
    _run_upgrade_install,
    _running_from_source_checkout,
    _upgrade_command,
    _validate_target_version,
    _validate_upgraded_install,
    _validated_pypi_url,
    cmd_upgrade,
)
from tests.upgrade_scenario_helpers import materialize_upgrade_scenario


class TestDetectInstallType:
    def test_detects_pipx_from_executable_path(self):
        detected = _detect_install_type(
            executable="/Users/me/.local/pipx/venvs/slopmop/bin/python",
            prefix="/Users/me/.local/pipx/venvs/slopmop",
            base_prefix="/usr/local/Cellar/python/3.13",
            virtual_env=None,
            direct_url={},
        )
        assert detected == "pipx"

    def test_detects_active_virtualenv(self):
        detected = _detect_install_type(
            executable="/tmp/project/.venv/bin/python",
            prefix="/tmp/project/.venv",
            base_prefix="/opt/homebrew/Cellar/python/3.13",
            virtual_env="/tmp/project/.venv",
            direct_url={},
        )
        assert detected == "venv"

    def test_detects_active_virtualenv_without_virtual_env_var(self):
        detected = _detect_install_type(
            executable="/tmp/project/.venv/bin/python",
            prefix="/tmp/project/.venv",
            base_prefix="/opt/homebrew/Cellar/python/3.13",
            virtual_env=None,
            direct_url={},
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

    def test_rejects_unsupported_non_venv_non_pipx_install(self):
        try:
            _detect_install_type(
                executable="/usr/local/bin/python3",
                prefix="/usr/local",
                base_prefix="/usr/local",
                virtual_env="",
                direct_url={},
            )
        except RuntimeError as exc:
            assert "supports pipx installs or pip installs" in str(exc)
        else:
            raise AssertionError("expected unsupported install type to be rejected")


class TestMetadataHelpers:
    @patch("slopmop.cli.upgrade.distribution", side_effect=PackageNotFoundError)
    def test_distribution_direct_url_handles_missing_package(self, _mock_distribution):
        assert _distribution_direct_url() is None

    @patch("slopmop.cli.upgrade._distribution_direct_url", return_value=None)
    def test_is_editable_install_false_without_payload(self, _mock_direct_url):
        assert _is_editable_install(None) is False

    @patch("slopmop.cli.upgrade.subprocess.run")
    def test_installed_version_fresh_reads_version_in_subprocess(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["python"], returncode=0, stdout="0.9.1\n", stderr=""
        )
        assert _installed_version_fresh() == "0.9.1"

    @patch("slopmop.cli.upgrade.subprocess.run")
    def test_installed_version_fresh_raises_on_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["python"], returncode=1, stdout="", stderr="boom"
        )
        try:
            _installed_version_fresh()
        except UpgradeError as exc:
            assert "Failed to read upgraded slopmop version" in str(exc)
        else:
            raise AssertionError("expected fresh version lookup to fail")

    def test_running_from_source_checkout_true_when_repo_markers_exist(
        self, tmp_path: Path
    ):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        (tmp_path / ".git").write_text("gitdir: .git/modules/x\n")
        with patch("slopmop.cli.upgrade._module_root", return_value=tmp_path):
            assert _running_from_source_checkout() is True

    def test_running_from_source_checkout_false_for_installed_package(
        self, tmp_path: Path
    ):
        with patch("slopmop.cli.upgrade._module_root", return_value=tmp_path):
            assert _running_from_source_checkout() is False


class TestPypiVersionHelpers:
    def test_validated_pypi_url_rejects_unexpected_scheme(self):
        with patch("slopmop.cli.upgrade.PYPI_URL", "http://pypi.org/pypi/slopmop/json"):
            try:
                _validated_pypi_url()
            except UpgradeError as exc:
                assert "unexpected PyPI URL" in str(exc)
            else:
                raise AssertionError("expected invalid PyPI URL to be rejected")

    @patch(
        "slopmop.cli.upgrade.urllib.request.urlopen",
        side_effect=__import__("urllib.error").error.URLError("boom"),
    )
    def test_fetch_latest_pypi_version_wraps_fetch_failure(self, _mock_urlopen):
        try:
            _fetch_latest_pypi_version()
        except UpgradeError as exc:
            assert "Failed to fetch the latest slopmop version" in str(exc)
        else:
            raise AssertionError("expected fetch failure to raise UpgradeError")

    @patch("slopmop.cli.upgrade.urllib.request.urlopen")
    def test_fetch_latest_pypi_version_rejects_missing_version(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_response.read.return_value = b'{"info": {}}'
        mock_response.__iter__.return_value = iter([])
        mock_urlopen.return_value = mock_response
        with patch("slopmop.cli.upgrade.json.load", return_value={"info": {}}):
            try:
                _fetch_latest_pypi_version()
            except UpgradeError as exc:
                assert "did not return a valid latest version" in str(exc)
            else:
                raise AssertionError("expected missing PyPI version to fail")


class TestVersionValidation:
    def test_validate_target_version_rejects_invalid_versions(self):
        try:
            _validate_target_version("0.9.0", "not-a-version")
        except UpgradeError as exc:
            assert "Invalid version value" in str(exc)
        else:
            raise AssertionError("expected invalid target version to fail")

    def test_validate_target_version_rejects_downgrade(self):
        try:
            _validate_target_version("0.9.1", "0.9.0")
        except UpgradeError as exc:
            assert "Refusing to downgrade" in str(exc)
        else:
            raise AssertionError("expected downgrade to fail")


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

    def test_backup_state_writes_manifest_even_without_config(self, tmp_path: Path):
        (tmp_path / ".slopmop").mkdir()
        backup_dir = _backup_upgrade_state(
            tmp_path,
            from_version="0.9.0",
            target_version="0.9.2",
            install_type="pipx",
        )
        assert (backup_dir / "manifest.json").exists()
        assert not (backup_dir / ".sb_config.json").exists()


class TestInstallCommandHelpers:
    @patch("slopmop.cli.upgrade.shutil.which", return_value=None)
    def test_upgrade_command_for_pipx_requires_binary(self, _mock_which):
        try:
            _upgrade_command("pipx", "0.9.1")
        except UpgradeError as exc:
            assert "pipx is not available on PATH" in str(exc)
        else:
            raise AssertionError("expected missing pipx to fail")

    def test_upgrade_command_rejects_unknown_install_type(self):
        try:
            _upgrade_command("weird", "0.9.1")
        except UpgradeError as exc:
            assert "Unsupported install type" in str(exc)
        else:
            raise AssertionError("expected unsupported install type to fail")

    @patch("slopmop.cli.upgrade.subprocess.run")
    def test_run_upgrade_install_raises_on_subprocess_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["pip"], returncode=1, stdout="", stderr="kaboom"
        )
        try:
            _run_upgrade_install("venv", "0.9.1")
        except UpgradeError as exc:
            assert "Upgrade failed: kaboom" in str(exc)
        else:
            raise AssertionError("expected install failure to raise UpgradeError")

    @patch("slopmop.cli.upgrade.subprocess.run")
    def test_validate_upgraded_install_adds_verbose_flag(
        self, mock_run, tmp_path: Path
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["python"], returncode=0
        )
        _validate_upgraded_install(tmp_path, True)
        command = mock_run.call_args.args[0]
        assert command[-1] == "--verbose"


class TestUpgradeCommand:
    @patch("slopmop.cli.upgrade._running_from_source_checkout", return_value=True)
    def test_upgrade_rejects_source_checkout(self, _mock_checkout, tmp_path, capsys):
        args = argparse.Namespace(
            project_root=str(tmp_path),
            check=True,
            to_version=None,
            verbose=False,
        )
        assert cmd_upgrade(args) == 1
        assert (
            "must be run from an installed slopmop package" in capsys.readouterr().err
        )

    @patch("slopmop.cli.upgrade._print_check_plan")
    @patch("slopmop.cli.upgrade._validate_target_version")
    @patch("slopmop.cli.upgrade._resolve_target_version", return_value="0.9.1")
    @patch("slopmop.cli.upgrade._detect_install_type", return_value="venv")
    @patch("slopmop.cli.upgrade._installed_version", return_value="0.9.0")
    @patch("slopmop.cli.upgrade._running_from_source_checkout", return_value=False)
    def test_check_mode_does_not_mutate(
        self,
        _mock_checkout,
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
    @patch("slopmop.cli.upgrade._installed_version_fresh", return_value="0.9.1")
    @patch("slopmop.cli.upgrade._installed_version", return_value="0.9.0")
    @patch("slopmop.cli.upgrade._running_from_source_checkout", return_value=False)
    def test_upgrade_runs_backup_install_migrations_and_validation(
        self,
        _mock_checkout,
        _mock_installed,
        _mock_installed_fresh,
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
    @patch("slopmop.cli.upgrade._resolve_target_version", return_value="0.9.0")
    @patch("slopmop.cli.upgrade._detect_install_type", return_value="venv")
    @patch("slopmop.cli.upgrade._installed_version", return_value="0.9.0")
    @patch("slopmop.cli.upgrade._running_from_source_checkout", return_value=False)
    def test_upgrade_noops_when_already_current(
        self,
        _mock_checkout,
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
        assert cmd_upgrade(args) == 0
        assert "already at 0.9.0" in capsys.readouterr().out

    @patch("slopmop.cli.upgrade._validate_upgraded_install")
    @patch("slopmop.cli.upgrade.run_upgrade_migrations", return_value=["m1"])
    @patch("slopmop.cli.upgrade._run_upgrade_install")
    @patch("slopmop.cli.upgrade._backup_upgrade_state")
    @patch("slopmop.cli.upgrade._validate_target_version")
    @patch("slopmop.cli.upgrade._resolve_target_version", return_value="0.9.1")
    @patch("slopmop.cli.upgrade._detect_install_type", return_value="venv")
    @patch("slopmop.cli.upgrade._installed_version_fresh", return_value="0.9.1")
    @patch("slopmop.cli.upgrade._installed_version", return_value="0.9.0")
    @patch("slopmop.cli.upgrade._running_from_source_checkout", return_value=False)
    def test_upgrade_reports_validation_failure(
        self,
        _mock_checkout,
        _mock_installed,
        _mock_installed_fresh,
        _mock_detect,
        _mock_target,
        _mock_validate_version,
        mock_backup,
        _mock_run_install,
        _mock_run_migrations,
        mock_validate,
        tmp_path,
        capsys,
    ):
        mock_backup.return_value = tmp_path / ".slopmop" / "backups" / "upgrade_x"
        mock_validate.return_value = subprocess.CompletedProcess(
            args=["python", "-m", "slopmop", "scour"],
            returncode=1,
            stdout="validation blew up",
            stderr="",
        )
        args = argparse.Namespace(
            project_root=str(tmp_path),
            check=False,
            to_version=None,
            verbose=True,
        )
        assert cmd_upgrade(args) == 1
        err = capsys.readouterr().err
        assert "validation failed" in err
        assert "validation blew up" in err

    @patch("slopmop.cli.upgrade._validate_target_version")
    @patch("slopmop.cli.upgrade._resolve_target_version", return_value="0.9.1")
    @patch(
        "slopmop.cli.upgrade._detect_install_type",
        side_effect=UpgradeError("bad install"),
    )
    @patch("slopmop.cli.upgrade._installed_version", return_value="0.9.0")
    @patch("slopmop.cli.upgrade._running_from_source_checkout", return_value=False)
    def test_upgrade_fails_for_unsupported_install(
        self,
        _mock_checkout,
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

    @pytest.mark.parametrize(
        "scenario_name",
        [
            "hierarchical_python_repo",
            "flat_python_repo",
            "hierarchical_applicability_repo",
            "flat_applicability_repo",
        ],
    )
    @patch("slopmop.cli.upgrade._validate_upgraded_install")
    @patch("slopmop.cli.upgrade._run_upgrade_install")
    @patch("slopmop.cli.upgrade._installed_version_fresh")
    @patch("slopmop.cli.upgrade._detect_install_type", return_value="venv")
    @patch("slopmop.cli.upgrade._installed_version")
    @patch("slopmop.cli.upgrade._running_from_source_checkout", return_value=False)
    def test_upgrade_runs_real_migrations_for_fixture_scenarios(
        self,
        _mock_checkout,
        _mock_installed,
        _mock_detect,
        _mock_installed_fresh,
        _mock_run_install,
        mock_validate,
        scenario_name,
        tmp_path,
        capsys,
    ):
        before, expected, meta = materialize_upgrade_scenario(tmp_path, scenario_name)
        _mock_installed.return_value = meta["from_version"]
        _mock_installed_fresh.return_value = meta["to_version"]
        mock_validate.return_value = subprocess.CompletedProcess(
            args=["python", "-m", "slopmop", "swab"],
            returncode=0,
            stdout="",
            stderr="",
        )
        args = argparse.Namespace(
            project_root=str(tmp_path),
            check=False,
            to_version=meta["to_version"],
            verbose=False,
        )

        assert cmd_upgrade(args) == 0

        out = capsys.readouterr().out
        assert (
            f"Upgraded slopmop: {meta['from_version']} -> {meta['to_version']}" in out
        )
        assert f"🔄 Migrations: {', '.join(meta['applied_migrations'])}" in out

        upgraded = json.loads(
            (tmp_path / ".sb_config.json").read_text(encoding="utf-8")
        )
        assert upgraded == expected

        backups = sorted((tmp_path / ".slopmop" / "backups").iterdir())
        assert len(backups) == 1
        backup_dir = backups[0]
        manifest = json.loads(
            (backup_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["from_version"] == meta["from_version"]
        assert manifest["target_version"] == meta["to_version"]
        assert manifest["install_type"] == "venv"
        assert (
            json.loads((backup_dir / ".sb_config.json").read_text(encoding="utf-8"))
            == before
        )


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


class TestMissingDependencyGuard:
    """Tests for graceful handling when packaging is absent."""

    def test_require_packaging_passes_when_available(self):
        """No error raised when packaging is installed (the normal case)."""
        assert _require_packaging() is None

    def test_require_packaging_raises_when_missing(self):
        """MissingDependencyError raised when packaging is not installed."""
        import builtins

        _real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "packaging.version":
                raise ModuleNotFoundError("No module named 'packaging'")
            return _real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_fake_import):
            with pytest.raises(MissingDependencyError) as exc_info:
                _require_packaging()
        assert "packaging" in str(exc_info.value)
        assert "upgrade" in str(exc_info.value)
        assert "pipx inject" in str(exc_info.value)

    def test_cmd_upgrade_raises_missing_dep_when_packaging_absent(self, tmp_path):
        """cmd_upgrade raises MissingDependencyError, not ModuleNotFoundError."""
        import builtins

        _real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "packaging.version":
                raise ModuleNotFoundError("No module named 'packaging'")
            return _real_import(name, *args, **kwargs)

        args = argparse.Namespace(
            project_root=str(tmp_path),
            check=True,
            to_version=None,
            verbose=False,
        )
        with (
            patch("builtins.__import__", side_effect=_fake_import),
            patch(
                "slopmop.cli.upgrade._running_from_source_checkout", return_value=False
            ),
        ):
            with pytest.raises(MissingDependencyError):
                cmd_upgrade(args)

    def test_missing_dependency_error_attributes(self):
        err = MissingDependencyError(
            package="packaging", verb="upgrade", reason="version comparison"
        )
        assert err.package == "packaging"
        assert err.verb == "upgrade"
        assert isinstance(err, ImportError)
