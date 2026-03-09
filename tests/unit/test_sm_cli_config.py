"""Config-command tests split out from test_sm_cli for code-sprawl limits."""

import argparse
import json
from unittest.mock import MagicMock, patch

from slopmop.cli.config import cmd_config
from slopmop.sm import create_parser


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

    def test_config_no_args_counts_nested_disabled_gates(self, tmp_path, capsys):
        """No-args summary should include nested gate enabled:false state."""
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
            enable=None,
            disable=None,
            include_dir=None,
            exclude_dir=None,
            json=None,
            swabbing_time=None,
        )

        result = cmd_config(args)

        assert result == 0
        out = capsys.readouterr().out
        summary_line = next(
            (line.strip() for line in out.splitlines() if "applicable gates" in line),
            "",
        )
        assert "disabled" in summary_line
        disabled_count = int(summary_line.split(",")[-1].split("disabled")[0].strip())
        assert disabled_count >= 1

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

        result = cmd_config(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "gate: myopia:vulnerability-blindness.py" in out
        assert "❌ DISABLED" in out

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
