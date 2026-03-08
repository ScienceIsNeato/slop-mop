"""Tests for cmd_config command handler."""

import argparse
import json
from unittest.mock import MagicMock, patch

from slopmop.cli.config import cmd_config
from slopmop.sm import create_parser


def _mock_registry_for_vuln_gate(applicable: bool = True) -> MagicMock:
    """Build a deterministic registry stub for vulnerability gate tests."""
    mock_registry = MagicMock()
    mock_check = MagicMock()
    mock_check.is_applicable.return_value = applicable
    mock_check.skip_reason.return_value = "no source files found"
    mock_registry.get_check.return_value = mock_check
    mock_registry.list_checks.return_value = ["myopia:vulnerability-blindness.py"]
    definition = MagicMock()
    definition.name = "Vulnerability Blindness"
    mock_registry.get_definition.return_value = definition
    return mock_registry


class TestCmdConfig:
    """Tests for cmd_config command handler."""

    def test_show_config(self, tmp_path, capsys):
        """--show displays configuration."""
        config = {"laziness": {"enabled": True}}
        (tmp_path / ".sb_config.json").write_text(json.dumps(config))

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=True,
            enable=None,
            disable=None,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=None,
        )

        with patch("slopmop.checks.ensure_checks_registered"):
            with patch("slopmop.cli.config.get_registry") as mock_registry:
                mock_reg = MagicMock()
                mock_reg.list_checks.return_value = ["overconfidence:untested-code.py"]
                mock_reg.get_definition.return_value = MagicMock(name="Python Tests")
                mock_registry.return_value = mock_reg

                result = cmd_config(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Configuration" in captured.out
        assert "Available Quality Gates" in captured.out
        assert "Run 'sm config --show' to see all gates." not in captured.out

    def test_config_no_args_shows_usage_hints(self, tmp_path, capsys):
        """No args prints usage/help summary instead of full gate list."""
        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=False,
            enable=None,
            disable=None,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=None,
        )

        with patch("slopmop.checks.ensure_checks_registered"):
            with patch("slopmop.cli.config.get_registry") as mock_registry:
                mock_reg = MagicMock()
                mock_reg.list_checks.return_value = ["deceptiveness:bogus-tests.js"]
                mock_registry.return_value = mock_reg

                result = cmd_config(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Usage:" in captured.out
        assert "Run 'sm config --show' to see all gates." in captured.out
        assert "Available Quality Gates" not in captured.out

    def test_config_registers_custom_gates(self, tmp_path):
        """cmd_config should register custom gates from config for management."""
        (tmp_path / ".sb_config.json").write_text(
            json.dumps(
                {
                    "custom_gates": [
                        {
                            "name": "x-custom",
                            "command": "echo ok",
                        }
                    ]
                }
            )
        )
        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=False,
            enable=None,
            disable=None,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=None,
        )

        with (
            patch("slopmop.checks.ensure_checks_registered"),
            patch("slopmop.checks.custom.register_custom_gates") as mock_register,
            patch("slopmop.cli.config.get_registry") as mock_registry,
        ):
            mock_reg = MagicMock()
            mock_reg.list_checks.return_value = []
            mock_registry.return_value = mock_reg
            result = cmd_config(args)

        assert result == 0
        mock_register.assert_called_once()

    def test_enable_gate(self, tmp_path):
        """--enable adds gate to enabled list."""
        # Make vulnerability-blindness applicable (needs source files)
        (tmp_path / "main.py").write_text("print('hello')\n")
        (tmp_path / ".sb_config.json").write_text(
            json.dumps({"disabled_gates": ["myopia:vulnerability-blindness.py"]})
        )

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=False,
            enable="myopia:vulnerability-blindness.py",
            disable=None,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=None,
        )

        with (
            patch("slopmop.checks.ensure_checks_registered"),
            patch(
                "slopmop.cli.config.get_registry",
                return_value=_mock_registry_for_vuln_gate(applicable=True),
            ),
        ):
            result = cmd_config(args)

        assert result == 0
        config = json.loads((tmp_path / ".sb_config.json").read_text())
        assert "myopia:vulnerability-blindness.py" not in config.get(
            "disabled_gates", []
        )

    def test_enable_gate_not_applicable(self, tmp_path, capsys):
        """--enable refuses gates that cannot apply to this repo."""
        (tmp_path / ".sb_config.json").write_text(
            json.dumps({"disabled_gates": ["myopia:vulnerability-blindness.py"]})
        )

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=False,
            enable="myopia:vulnerability-blindness.py",
            disable=None,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=None,
        )

        with (
            patch("slopmop.checks.ensure_checks_registered"),
            patch(
                "slopmop.cli.config.get_registry",
                return_value=_mock_registry_for_vuln_gate(applicable=False),
            ),
        ):
            result = cmd_config(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Cannot enable myopia:vulnerability-blindness.py" in captured.out
        assert "re-run: sm init --non-interactive" in captured.out

    def test_enable_gate_updates_nested_enabled_flag(self, tmp_path):
        """--enable also updates canonical nested gate enabled flag."""
        (tmp_path / "main.py").write_text("print('hello')\n")
        (tmp_path / ".sb_config.json").write_text(
            json.dumps(
                {
                    "myopia": {
                        "gates": {
                            "vulnerability-blindness.py": {
                                "enabled": False,
                            }
                        }
                    }
                }
            )
        )

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=False,
            enable="myopia:vulnerability-blindness.py",
            disable=None,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=None,
        )

        with (
            patch("slopmop.checks.ensure_checks_registered"),
            patch(
                "slopmop.cli.config.get_registry",
                return_value=_mock_registry_for_vuln_gate(applicable=True),
            ),
        ):
            result = cmd_config(args)

        assert result == 0
        config = json.loads((tmp_path / ".sb_config.json").read_text())
        assert (
            config["myopia"]["gates"]["vulnerability-blindness.py"]["enabled"] is True
        )

    def test_show_uses_nested_enabled_flag(self, tmp_path, capsys):
        """--show should mark nested enabled:false gates as disabled."""
        (tmp_path / "main.py").write_text("print('hello')\n")
        (tmp_path / ".sb_config.json").write_text(
            json.dumps(
                {
                    "myopia": {
                        "gates": {
                            "vulnerability-blindness.py": {
                                "enabled": False,
                            }
                        }
                    }
                }
            )
        )

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=True,
            enable=None,
            disable=None,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=None,
        )

        with (
            patch("slopmop.checks.ensure_checks_registered"),
            patch(
                "slopmop.cli.config.get_registry",
                return_value=_mock_registry_for_vuln_gate(applicable=True),
            ),
        ):
            result = cmd_config(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "gate: myopia:vulnerability-blindness.py" in out
        assert "❌ DISABLED" in out

    def test_disable_gate_sets_flat_and_nested_flags(self, tmp_path):
        """--disable stores both flat disabled list and nested enabled:false."""
        gate = "myopia:vulnerability-blindness.py"
        (tmp_path / ".sb_config.json").write_text(json.dumps({}))

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=False,
            enable=None,
            disable=gate,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=None,
        )

        with patch("slopmop.checks.ensure_checks_registered"):
            result = cmd_config(args)

        assert result == 0
        config = json.loads((tmp_path / ".sb_config.json").read_text())
        assert gate in config["disabled_gates"]
        assert (
            config["myopia"]["gates"]["vulnerability-blindness.py"]["enabled"] is False
        )

    def test_disable_gate_already_disabled_flat_list(self, tmp_path, capsys):
        """--disable is a no-op when gate is already in disabled_gates."""
        gate = "myopia:vulnerability-blindness.py"
        (tmp_path / ".sb_config.json").write_text(
            json.dumps({"disabled_gates": [gate]})
        )

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=False,
            enable=None,
            disable=gate,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=None,
        )

        with patch("slopmop.checks.ensure_checks_registered"):
            result = cmd_config(args)

        assert result == 0
        assert f"{gate} is already disabled" in capsys.readouterr().out

    def test_disable_gate_already_disabled_nested_flag(self, tmp_path, capsys):
        """--disable is a no-op when nested config already has enabled:false."""
        gate = "myopia:vulnerability-blindness.py"
        (tmp_path / ".sb_config.json").write_text(
            json.dumps(
                {
                    "myopia": {
                        "gates": {"vulnerability-blindness.py": {"enabled": False}}
                    }
                }
            )
        )

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=False,
            enable=None,
            disable=gate,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=None,
        )

        with patch("slopmop.checks.ensure_checks_registered"):
            result = cmd_config(args)

        assert result == 0
        assert f"{gate} is already disabled" in capsys.readouterr().out

    def test_enable_non_scoped_gate_treated_as_enabled(self, tmp_path, capsys):
        """Non-scoped gate names are treated as enabled unless explicitly disabled."""
        gate = "custom-style-check"
        (tmp_path / ".sb_config.json").write_text(json.dumps({"disabled_gates": {}}))

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=False,
            enable=gate,
            disable=None,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=None,
        )

        with (
            patch("slopmop.checks.ensure_checks_registered"),
            patch(
                "slopmop.cli.config.get_registry",
                return_value=_mock_registry_for_vuln_gate(applicable=True),
            ),
        ):
            result = cmd_config(args)

        assert result == 0
        assert f"{gate} is already enabled" in capsys.readouterr().out

    def test_config_swabbing_time_parser(self):
        """config --swabbing-time flag parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["config", "--swabbing-time", "45"])
        assert args.verb == "config"
        assert args.swabbing_time == 45

    def test_set_swabbing_time(self, tmp_path):
        """--swabbing-time updates config file."""
        (tmp_path / ".sb_config.json").write_text(json.dumps({"version": "1.0"}))

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=False,
            enable=None,
            disable=None,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=30,
        )

        with patch("slopmop.checks.ensure_checks_registered"):
            result = cmd_config(args)

        assert result == 0
        config = json.loads((tmp_path / ".sb_config.json").read_text())
        assert config["swabbing_time"] == 30

    def test_disable_swabbing_time(self, tmp_path):
        """--swabbing-time 0 removes swabbing_time from config."""
        (tmp_path / ".sb_config.json").write_text(
            json.dumps({"version": "1.0", "swabbing_time": 20})
        )

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=False,
            enable=None,
            disable=None,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=0,
        )

        with patch("slopmop.checks.ensure_checks_registered"):
            result = cmd_config(args)

        assert result == 0
        config = json.loads((tmp_path / ".sb_config.json").read_text())
        assert "swabbing_time" not in config
