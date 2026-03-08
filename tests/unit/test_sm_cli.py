"""Tests for sb.py CLI functions.

Tests the CLI parser, command handlers, and helper functions.
"""

import argparse
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from slopmop.cli.ci import cmd_ci
from slopmop.cli.config import cmd_config
from slopmop.cli.detection import _normalize_language_key, detect_project_type
from slopmop.cli.help import cmd_help
from slopmop.cli.hooks import (
    SB_HOOK_MARKER,
    _generate_hook_script,
    _get_git_hooks_dir,
    _parse_hook_info,
    cmd_commit_hooks,
)
from slopmop.cli.init import prompt_user, prompt_yes_no
from slopmop.sm import create_parser, load_config, main, setup_logging


class TestLoadConfig:
    """Tests for load_config function."""

    def test_loads_config_from_file(self, tmp_path):
        """Config is loaded from .sb_config.json."""
        config = {"laziness": {"enabled": True}}
        config_file = tmp_path / ".sb_config.json"
        config_file.write_text(json.dumps(config))

        result = load_config(tmp_path)
        assert result == config

    def test_returns_empty_dict_if_no_config(self, tmp_path):
        """Returns empty dict if config file doesn't exist."""
        result = load_config(tmp_path)
        assert result == {}

    def test_returns_empty_dict_on_invalid_json(self, tmp_path):
        """Returns empty dict if config file has invalid JSON."""
        config_file = tmp_path / ".sb_config.json"
        config_file.write_text("not valid json {{{")

        result = load_config(tmp_path)
        assert result == {}

    def test_uses_env_var_override(self, tmp_path):
        """SB_CONFIG_FILE env var overrides default path."""
        config = {"override": True}
        custom_config = tmp_path / "custom.json"
        custom_config.write_text(json.dumps(config))

        with patch.dict(os.environ, {"SB_CONFIG_FILE": str(custom_config)}):
            result = load_config(tmp_path)
            assert result == {"override": True}


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_calls_basic_config_with_debug(self):
        """Verbose mode calls basicConfig with DEBUG."""
        import logging

        with patch.object(logging, "basicConfig") as mock_config:
            setup_logging(verbose=True)
            mock_config.assert_called_once()
            call_kwargs = mock_config.call_args[1]
            assert call_kwargs["level"] == logging.DEBUG

    def test_calls_basic_config_with_info(self):
        """Default mode calls basicConfig with INFO."""
        import logging

        with patch.object(logging, "basicConfig") as mock_config:
            setup_logging(verbose=False)
            mock_config.assert_called_once()
            call_kwargs = mock_config.call_args[1]
            assert call_kwargs["level"] == logging.INFO


class TestCreateParser:
    """Tests for create_parser function."""

    def test_creates_parser(self):
        """Parser is created successfully."""
        parser = create_parser()
        assert parser is not None
        assert parser.prog == "./sm"

    def test_swab_subcommand(self):
        """Swab subcommand parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["swab"])
        assert args.verb == "swab"

    def test_scour_subcommand(self):
        """Scour subcommand parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["scour"])
        assert args.verb == "scour"

    def test_swab_with_quality_gates(self):
        """Swab with --quality-gates parses correctly."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "swab",
                "-g",
                "overconfidence:untested-code.py",
                "overconfidence:coverage-gaps.py",
            ]
        )
        assert args.verb == "swab"
        assert args.quality_gates == [
            "overconfidence:untested-code.py",
            "overconfidence:coverage-gaps.py",
        ]

    def test_swabbing_time_flag(self):
        """--swabbing-time flag parses correctly on swab."""
        parser = create_parser()
        args = parser.parse_args(["swab", "--swabbing-time", "30"])
        assert args.verb == "swab"
        assert args.swabbing_time == 30

    def test_swabbing_time_default_none(self):
        """--swabbing-time defaults to None when not provided."""
        parser = create_parser()
        args = parser.parse_args(["scour"])
        assert args.swabbing_time is None

    def test_swabbing_time_zero_disables(self):
        """--swabbing-time 0 parses and signals 'no limit'."""
        parser = create_parser()
        args = parser.parse_args(["swab", "--swabbing-time", "0"])
        assert args.swabbing_time == 0

    def test_no_cache_flag_default_false(self):
        """--no-cache defaults to False when not provided."""
        parser = create_parser()
        args = parser.parse_args(["swab"])
        assert args.no_cache is False

    def test_no_cache_flag_set(self):
        """--no-cache parses correctly on swab."""
        parser = create_parser()
        args = parser.parse_args(["swab", "--no-cache"])
        assert args.no_cache is True

    def test_no_cache_flag_on_scour(self):
        """--no-cache parses correctly on scour."""
        parser = create_parser()
        args = parser.parse_args(["scour", "--no-cache"])
        assert args.no_cache is True

    def test_config_subcommand(self):
        """Config subcommand parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["config", "--show"])
        assert args.verb == "config"
        assert args.show is True

    def test_config_enable(self):
        """Config --enable parses correctly."""
        parser = create_parser()
        args = parser.parse_args(
            ["config", "--enable", "myopia:vulnerability-blindness.py"]
        )
        assert args.verb == "config"
        assert args.enable == "myopia:vulnerability-blindness.py"

    def test_help_subcommand(self):
        """Help subcommand parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["help", "laziness:sloppy-formatting.py"])
        assert args.verb == "help"
        assert args.gate == "laziness:sloppy-formatting.py"

    def test_init_subcommand(self):
        """Init subcommand parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["init", "--non-interactive"])
        assert args.verb == "init"
        assert args.non_interactive is True

    def test_commit_hooks_status(self):
        """Commit-hooks status parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["commit-hooks", "status"])
        assert args.verb == "commit-hooks"
        assert args.hooks_action == "status"

    def test_commit_hooks_install(self):
        """Commit-hooks install parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["commit-hooks", "install", "swab"])
        assert args.verb == "commit-hooks"
        assert args.hooks_action == "install"
        assert args.hook_verb == "swab"

    def test_commit_hooks_uninstall(self):
        """Commit-hooks uninstall parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["commit-hooks", "uninstall"])
        assert args.verb == "commit-hooks"
        assert args.hooks_action == "uninstall"


class TestDetectProjectType:
    """Tests for detect_project_type function."""

    @pytest.fixture(autouse=True)
    def _disable_scc_by_default(self):
        """Keep legacy marker-based tests deterministic."""
        with patch(
            "slopmop.cli.detection._detect_languages_with_scc", return_value=None
        ):
            yield

    def test_detects_python_project_from_pyproject(self, tmp_path):
        """Detects Python from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]")
        result = detect_project_type(tmp_path)
        assert result["has_python"] is True
        assert result["has_pytest"] is True

    def test_detects_python_project_from_requirements(self, tmp_path):
        """Detects Python from requirements.txt."""
        (tmp_path / "requirements.txt").write_text("flask==2.0")
        result = detect_project_type(tmp_path)
        assert result["has_python"] is True

    def test_detects_javascript_project(self, tmp_path):
        """Detects JavaScript from package.json."""
        (tmp_path / "package.json").write_text("{}")
        result = detect_project_type(tmp_path)
        assert result["has_javascript"] is True

    def test_detects_jest(self, tmp_path):
        """Detects Jest from package.json devDependencies."""
        pkg = {"devDependencies": {"jest": "^29.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        result = detect_project_type(tmp_path)
        assert result["has_jest"] is True

    def test_detects_jest_from_nested_package_json(self, tmp_path):
        """Detects Jest from nested package.json in monorepo layouts."""
        pkg = {"devDependencies": {"jest": "^29.0.0"}}
        (tmp_path / "client").mkdir()
        (tmp_path / "client" / "package.json").write_text(json.dumps(pkg))
        result = detect_project_type(tmp_path)
        assert result["has_jest"] is True

    def test_detects_test_directories(self, tmp_path):
        """Detects test directories."""
        (tmp_path / "tests").mkdir()
        result = detect_project_type(tmp_path)
        assert result["has_tests_dir"] is True
        assert "tests" in result["test_dirs"]

    def test_detects_nested_test_directories(self, tmp_path):
        """Detects nested test directories in monorepo layouts."""
        (tmp_path / "server" / "tests").mkdir(parents=True)
        (tmp_path / "client" / "test").mkdir(parents=True)
        result = detect_project_type(tmp_path)
        assert result["has_tests_dir"] is True
        assert "server/tests" in result["test_dirs"]
        assert "client/test" in result["test_dirs"]

    def test_ignores_test_directories_in_excluded_paths(self, tmp_path):
        """Does not count node_modules test directories."""
        (tmp_path / "node_modules" / "foo" / "tests").mkdir(parents=True)
        result = detect_project_type(tmp_path)
        assert result["has_tests_dir"] is False
        assert result["test_dirs"] == []

    def test_detects_pytest_from_nested_config(self, tmp_path):
        """Detects pytest from nested pytest.ini."""
        (tmp_path / "server").mkdir()
        (tmp_path / "server" / "pytest.ini").write_text("[pytest]\n")
        result = detect_project_type(tmp_path)
        assert result["has_pytest"] is True

    def test_recommends_gates_for_python(self, tmp_path):
        """Recommends appropriate gates for Python-only projects."""
        (tmp_path / "setup.py").write_text("")
        result = detect_project_type(tmp_path)
        assert "recommended_gates" in result

    def test_recommends_gates_for_mixed(self, tmp_path):
        """Recommends appropriate gates for mixed Python/JS projects."""
        (tmp_path / "setup.py").write_text("")
        (tmp_path / "package.json").write_text("{}")
        result = detect_project_type(tmp_path)
        assert "recommended_gates" in result

    def test_detects_typescript_from_tsconfig(self, tmp_path):
        """Detects TypeScript from tsconfig.json."""
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        result = detect_project_type(tmp_path)
        assert result["has_typescript"] is True
        assert result["has_javascript"] is True  # TS implies JS

    def test_detects_typescript_from_ci_config(self, tmp_path):
        """Detects TypeScript from tsconfig.ci.json."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.ci.json").write_text('{"compilerOptions": {}}')
        result = detect_project_type(tmp_path)
        assert result["has_typescript"] is True

    def test_typescript_recommends_types_gate(self, tmp_path):
        """TypeScript projects recommend type-blindness.js gate."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        result = detect_project_type(tmp_path)
        assert "overconfidence:type-blindness.js" in result["recommended_gates"]

    def test_prefers_scc_detection_when_available(self, tmp_path):
        """scc output should drive language flags when available."""
        with patch(
            "slopmop.cli.detection._detect_languages_with_scc",
            return_value={"typescript"},
        ):
            result = detect_project_type(tmp_path)

        assert result["language_detector"] == "scc"
        assert result["has_typescript"] is True
        assert result["has_javascript"] is True  # TS implies JS
        assert "overconfidence:type-blindness.js" in result["recommended_gates"]

    def test_empty_scc_result_falls_back_to_manifest_detection(self, tmp_path):
        """Empty scc output should not suppress manifest-based language detection."""
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n")
        mock_scc = MagicMock(returncode=0, stdout="{}")
        with (
            patch("slopmop.cli.detection.find_tool", return_value="/usr/bin/scc"),
            patch("subprocess.run", return_value=mock_scc),
        ):
            result = detect_project_type(tmp_path)

        assert result["language_detector"] == "manifest"
        assert result["has_python"] is True

    def test_normalize_language_key_handles_cplusplus_header(self):
        """Normalization should preserve C++ semantics in keys."""
        assert _normalize_language_key("C++ Header") == "cplusplusheader"

    def test_dart_detection_suggests_flutter_custom_gates(self, tmp_path):
        """Dart repos should get Flutter custom gates and built-in Dart gates."""
        with (
            patch(
                "slopmop.cli.detection._detect_languages_with_scc",
                return_value={"dart"},
            ),
            patch(
                "slopmop.cli.detection.find_tool",
                side_effect=lambda name, _root: f"/usr/bin/{name}",
            ),
        ):
            result = detect_project_type(tmp_path)

        assert result["has_dart"] is True
        names = {gate["name"] for gate in result["suggested_custom_gates"]}
        assert "flutter-analyze" in names
        assert "flutter-test" in names
        assert "dart-format-check" in names

        by_name = {gate["name"]: gate for gate in result["suggested_custom_gates"]}
        assert "find . -name pubspec.yaml" in by_name["flutter-analyze"]["command"]
        assert "find . -name pubspec.yaml" in by_name["flutter-test"]["command"]
        assert (
            "dart format --output=none --set-exit-if-changed"
            in by_name["dart-format-check"]["command"]
        )
        assert (
            "engine.stamp: Operation not permitted"
            in by_name["dart-format-check"]["command"]
        )
        assert "overconfidence:coverage-gaps.dart" in result["recommended_gates"]
        assert "deceptiveness:bogus-tests.dart" in result["recommended_gates"]
        assert "laziness:generated-artifacts.dart" in result["recommended_gates"]

    def test_dart_detection_omits_flutter_custom_gates_when_tools_missing(
        self, tmp_path
    ):
        """Dart custom gates should not be suggested when flutter/dart tools are missing."""
        with (
            patch(
                "slopmop.cli.detection._detect_languages_with_scc",
                return_value={"dart"},
            ),
            patch("slopmop.cli.detection.find_tool", return_value=None),
        ):
            result = detect_project_type(tmp_path)

        assert result["has_dart"] is True
        assert result["suggested_custom_gates"] == []
        assert "overconfidence:coverage-gaps.dart" in result["recommended_gates"]


class TestPromptFunctions:
    """Tests for prompt_user and prompt_yes_no."""

    def test_prompt_user_returns_input(self):
        """prompt_user returns user input."""
        with patch("builtins.input", return_value="my answer"):
            result = prompt_user("Question?")
            assert result == "my answer"

    def test_prompt_user_returns_default(self):
        """prompt_user returns default on empty input."""
        with patch("builtins.input", return_value=""):
            result = prompt_user("Question?", default="default value")
            assert result == "default value"

    def test_prompt_yes_no_yes(self):
        """prompt_yes_no returns True for 'y'."""
        with patch("builtins.input", return_value="y"):
            result = prompt_yes_no("Continue?")
            assert result is True

    def test_prompt_yes_no_no(self):
        """prompt_yes_no returns False for 'n'."""
        with patch("builtins.input", return_value="n"):
            result = prompt_yes_no("Continue?")
            assert result is False

    def test_prompt_yes_no_default_true(self):
        """prompt_yes_no returns True on empty with default=True."""
        with patch("builtins.input", return_value=""):
            result = prompt_yes_no("Continue?", default=True)
            assert result is True

    def test_prompt_yes_no_default_false(self):
        """prompt_yes_no returns False on empty with default=False."""
        with patch("builtins.input", return_value=""):
            result = prompt_yes_no("Continue?", default=False)
            assert result is False


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

        with patch("slopmop.checks.ensure_checks_registered"):
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

        with patch("slopmop.checks.ensure_checks_registered"):
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

        with patch("slopmop.checks.ensure_checks_registered"):
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

        with patch("slopmop.checks.ensure_checks_registered"):
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

        with patch("slopmop.checks.ensure_checks_registered"):
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


class TestCmdHelp:
    """Tests for cmd_help command handler."""

    def test_help_all_gates(self, capsys):
        """Help without gate shows all gates."""
        args = argparse.Namespace(gate=None)

        with patch("slopmop.checks.ensure_checks_registered"):
            with patch("slopmop.cli.config.get_registry") as mock_registry:
                mock_reg = MagicMock()
                mock_reg.list_checks.return_value = [
                    "overconfidence:untested-code.py",
                    "overconfidence:coverage-gaps.py",
                ]
                mock_reg.get_definition.return_value = MagicMock(
                    name="Test", auto_fix=False
                )
                mock_registry.return_value = mock_reg

                result = cmd_help(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Quality Gates" in captured.out

    def test_help_specific_gate(self, capsys):
        """Help for specific gate shows details."""
        args = argparse.Namespace(gate="overconfidence:untested-code.py")

        mock_check = MagicMock()
        mock_check.__doc__ = "Test documentation"

        with patch("slopmop.checks.ensure_checks_registered"):
            with patch("slopmop.cli.help.get_registry") as mock_registry:
                mock_reg = MagicMock()
                mock_reg.get_definition.return_value = MagicMock(
                    name="Python Tests",
                    flag="python-tests",
                    auto_fix=False,
                    depends_on=[],
                )
                mock_reg.get_check.return_value = mock_check
                mock_registry.return_value = mock_reg

                result = cmd_help(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Python Tests" in captured.out


class TestGitHooksFunctions:
    """Tests for git hooks helper functions."""

    def test_get_git_hooks_dir(self, tmp_path):
        """Returns hooks dir for git repo."""
        (tmp_path / ".git").mkdir()
        result = _get_git_hooks_dir(tmp_path)
        assert result == tmp_path / ".git" / "hooks"

    def test_get_git_hooks_dir_not_git(self, tmp_path):
        """Returns None for non-git directory."""
        result = _get_git_hooks_dir(tmp_path)
        assert result is None

    def test_generate_hook_script(self):
        """Generates valid hook script with swab verb."""
        script = _generate_hook_script("swab")
        assert "sm swab" in script
        assert "MANAGED BY SLOP-MOP" in script
        # Should use PATH-based sm lookup
        assert "command -v sm" in script
        # Should write structured output for LLM consumption
        assert "--json" in script
        assert "--output-file .slopmop/last_swab.json" in script
        assert "Structured results:" in script
        assert "mkdir -p .slopmop" in script

    def test_generate_hook_script_direct_verb(self):
        """Generates hook script when given a verb directly."""
        script = _generate_hook_script("scour")
        assert "sm scour" in script
        assert "# Command: sm scour" in script
        assert "--output-file .slopmop/last_scour.json" in script

    def test_parse_hook_info_new_format(self):
        """Parses new-format hook info (Command: sm verb)."""
        content = """# MANAGED BY SLOP-MOP
#!/bin/sh
# Command: sm swab
sm swab
"""
        result = _parse_hook_info(content)
        assert result is not None
        assert result["verb"] == "swab"
        assert result["managed"] is True

    def test_parse_hook_info_not_managed(self):
        """Returns None for non-managed hook."""
        content = "#!/bin/sh\necho hello"
        result = _parse_hook_info(content)
        assert result is None


class TestCmdCommitHooks:
    """Tests for cmd_commit_hooks command handler."""

    def test_status_no_git(self, tmp_path, capsys):
        """Status shows error for non-git dir."""
        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="status",
        )

        result = cmd_commit_hooks(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Not a git repository" in captured.out

    def test_status_no_hooks(self, tmp_path, capsys):
        """Status shows no hooks installed."""
        (tmp_path / ".git").mkdir()

        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="status",
        )

        result = cmd_commit_hooks(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Git Hooks Status" in captured.out

    def test_install_hook(self, tmp_path, capsys):
        """Install creates hook file with swab verb."""
        (tmp_path / ".git").mkdir()

        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="install",
            hook_verb="swab",
        )

        result = cmd_commit_hooks(args)

        assert result == 0
        hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
        assert hook_file.exists()
        assert "sm swab" in hook_file.read_text()

    def test_uninstall_hook(self, tmp_path, capsys):
        """Uninstall removes managed hooks."""
        (tmp_path / ".git" / "hooks").mkdir(parents=True)
        hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
        hook_file.write_text("# MANAGED BY SLOP-MOP\n# Command: sm swab\nsm swab")

        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="uninstall",
        )

        result = cmd_commit_hooks(args)

        assert result == 0
        assert not hook_file.exists()


class TestMain:
    """Tests for main entry point."""

    def test_main_no_args_shows_help(self, capsys):
        """Main with no args shows help."""
        result = main([])
        assert result == 0

    def test_main_version(self, capsys):
        """Main --version shows version."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0

    def test_main_swab_calls_cmd_swab(self):
        """Main routes swab to cmd_swab."""
        with patch("slopmop.cli.cmd_swab") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["swab"])
            mock_cmd.assert_called_once()
            assert result == 0

    def test_main_scour_calls_cmd_scour(self):
        """Main routes scour to cmd_scour."""
        with patch("slopmop.cli.cmd_scour") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["scour"])
            mock_cmd.assert_called_once()
            assert result == 0

    def test_main_config_calls_cmd_config(self):
        """Main routes config to cmd_config."""
        with patch("slopmop.cli.cmd_config") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["config", "--show"])
            mock_cmd.assert_called_once()
            assert result == 0

    def test_main_help_calls_cmd_help(self):
        """Main routes help to cmd_help."""
        with patch("slopmop.cli.cmd_help") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["help"])
            mock_cmd.assert_called_once()
            assert result == 0

    def test_main_commit_hooks_calls_cmd_commit_hooks(self):
        """Main routes commit-hooks to cmd_commit_hooks."""
        with patch("slopmop.cli.cmd_commit_hooks") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["commit-hooks", "status"])
            mock_cmd.assert_called_once()
            assert result == 0

    def test_main_ci_calls_cmd_ci(self):
        """Main routes ci to cmd_ci."""
        with patch("slopmop.cli.cmd_ci") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["ci"])
            mock_cmd.assert_called_once()
            assert result == 0


class TestCmdCi:
    """Tests for cmd_ci function."""

    def test_ci_no_pr_context(self, tmp_path):
        """Returns error when no PR context available."""
        args = argparse.Namespace(
            pr_number=None,
            watch=False,
            interval=30,
            project_root=str(tmp_path),
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = cmd_ci(args)

        assert result == 2  # No PR context error

    def test_ci_with_explicit_pr_number(self, tmp_path, capsys):
        """Uses explicit PR number when provided."""
        args = argparse.Namespace(
            pr_number=42,
            watch=False,
            interval=30,
            project_root=str(tmp_path),
        )

        # Mock gh pr checks returning all passed
        checks_response = json.dumps(
            [
                {"name": "test", "state": "completed", "bucket": "pass"},
            ]
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=checks_response, stderr=""
            )
            result = cmd_ci(args)

        captured = capsys.readouterr()
        assert result == 0
        assert "PR: #42" in captured.out
        assert "CI CLEAN" in captured.out

    def test_ci_with_failures(self, tmp_path, capsys):
        """Returns failure when checks fail."""
        args = argparse.Namespace(
            pr_number=1,
            watch=False,
            interval=30,
            project_root=str(tmp_path),
        )

        checks_response = json.dumps(
            [
                {"name": "passed-check", "state": "completed", "bucket": "pass"},
                {
                    "name": "failed-check",
                    "state": "completed",
                    "bucket": "fail",
                    "link": "https://example.com",
                },
            ]
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=checks_response, stderr=""
            )
            result = cmd_ci(args)

        captured = capsys.readouterr()
        assert result == 1
        assert "SLOP IN CI" in captured.out
        assert "failed-check" in captured.out

    def test_ci_in_progress_no_watch(self, tmp_path, capsys):
        """Returns exit code 1 with in-progress checks when not watching."""
        args = argparse.Namespace(
            pr_number=1,
            watch=False,
            interval=30,
            project_root=str(tmp_path),
        )

        checks_response = json.dumps(
            [
                {"name": "running-check", "state": "in_progress", "bucket": "pending"},
            ]
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=checks_response, stderr=""
            )
            result = cmd_ci(args)

        captured = capsys.readouterr()
        assert result == 1
        assert "CI IN PROGRESS" in captured.out
        assert "Use --watch" in captured.out

    def test_ci_no_checks(self, tmp_path, capsys):
        """Returns success when no checks found."""
        args = argparse.Namespace(
            pr_number=1,
            watch=False,
            interval=30,
            project_root=str(tmp_path),
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
            result = cmd_ci(args)

        captured = capsys.readouterr()
        assert result == 0
        assert "No CI checks found" in captured.out

    def test_ci_gh_not_found(self, tmp_path, capsys):
        """Returns error when gh CLI not available."""
        args = argparse.Namespace(
            pr_number=1,
            watch=False,
            interval=30,
            project_root=str(tmp_path),
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            result = cmd_ci(args)

        captured = capsys.readouterr()
        assert result == 2
        assert "gh" in captured.out.lower()


class TestScourDisablesFailFast:
    """Scour must never use fail-fast so every gate runs to completion."""

    def _make_args(self, tmp_path, no_fail_fast=False):
        return argparse.Namespace(
            project_root=str(tmp_path),
            quiet=True,
            verbose=False,
            no_fail_fast=no_fail_fast,
            no_auto_fix=True,
            static=True,
            clear_history=False,
            swabbing_time=None,
            json_output=False,
        )

    @patch("slopmop.cli.validate.ConsoleAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    def test_scour_forces_fail_fast_off(
        self,
        _mock_config,
        mock_reg,
        mock_executor_cls,
        _mock_reporter,
        _mock_adapter,
        tmp_path,
    ):
        """Scour always creates executor with fail_fast=False."""
        from slopmop.cli.validate import _run_validation

        mock_executor = MagicMock()
        mock_executor.run_checks.return_value = MagicMock(all_passed=True)
        mock_executor_cls.return_value = mock_executor

        _run_validation(self._make_args(tmp_path), ["gate1"], "scour")

        mock_executor_cls.assert_called_once()
        _, kwargs = mock_executor_cls.call_args
        assert kwargs["fail_fast"] is False

    @patch("slopmop.cli.validate.ConsoleAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    def test_scour_ignores_no_fail_fast_flag(
        self,
        _mock_config,
        mock_reg,
        mock_executor_cls,
        _mock_reporter,
        _mock_adapter,
        tmp_path,
    ):
        """Even with --no-fail-fast omitted, scour still disables fail-fast."""
        from slopmop.cli.validate import _run_validation

        mock_executor = MagicMock()
        mock_executor.run_checks.return_value = MagicMock(all_passed=True)
        mock_executor_cls.return_value = mock_executor

        # no_fail_fast=False means the user did NOT pass --no-fail-fast,
        # which normally means fail_fast=True. Scour overrides this.
        _run_validation(
            self._make_args(tmp_path, no_fail_fast=False), ["gate1"], "scour"
        )

        _, kwargs = mock_executor_cls.call_args
        assert kwargs["fail_fast"] is False

    @patch("slopmop.cli.validate.ConsoleAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    def test_swab_defaults_to_fail_fast(
        self,
        _mock_config,
        mock_reg,
        mock_executor_cls,
        _mock_reporter,
        _mock_adapter,
        tmp_path,
    ):
        """Swab defaults to fail_fast=True."""
        from slopmop.cli.validate import _run_validation

        mock_executor = MagicMock()
        mock_executor.run_checks.return_value = MagicMock(all_passed=True)
        mock_executor_cls.return_value = mock_executor

        _run_validation(self._make_args(tmp_path), ["gate1"], "swab")

        _, kwargs = mock_executor_cls.call_args
        assert kwargs["fail_fast"] is True

    @patch("slopmop.cli.validate.ConsoleAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    def test_swab_respects_no_fail_fast_flag(
        self,
        _mock_config,
        mock_reg,
        mock_executor_cls,
        _mock_reporter,
        _mock_adapter,
        tmp_path,
    ):
        """Swab with --no-fail-fast creates executor with fail_fast=False."""
        from slopmop.cli.validate import _run_validation

        mock_executor = MagicMock()
        mock_executor.run_checks.return_value = MagicMock(all_passed=True)
        mock_executor_cls.return_value = mock_executor

        _run_validation(self._make_args(tmp_path, no_fail_fast=True), ["gate1"], "swab")

        _, kwargs = mock_executor_cls.call_args
        assert kwargs["fail_fast"] is False


class TestSetupDynamicDisplay:
    """Tests for _setup_dynamic_display helper in validate.py."""

    def test_wires_all_callbacks_and_returns_display(self, tmp_path):
        """_setup_dynamic_display wires callbacks and returns started display."""
        from unittest.mock import MagicMock, patch

        from slopmop.cli.validate import _setup_dynamic_display
        from slopmop.core.executor import CheckExecutor
        from slopmop.reporting.console import ConsoleReporter

        executor = MagicMock(spec=CheckExecutor)
        reporter = MagicMock(spec=ConsoleReporter)

        with patch("slopmop.cli.validate.DynamicDisplay") as MockDisplay:
            mock_display = MagicMock()
            MockDisplay.return_value = mock_display

            result, deferred = _setup_dynamic_display(
                executor, reporter, quiet=True, project_root=tmp_path
            )

        assert result is mock_display
        assert deferred == []  # empty list initially
        mock_display.start.assert_called_once()
        executor.set_start_callback.assert_called_once()
        executor.set_disabled_callback.assert_called_once()
        executor.set_na_callback.assert_called_once()
        executor.set_total_callback.assert_called_once()
        executor.set_pending_callback.assert_called_once()
        executor.set_progress_callback.assert_called_once()

    def test_combined_callback_routes_failures_to_reporter(self, tmp_path):
        """Combined callback passes failed results to reporter but not passing ones."""
        from unittest.mock import MagicMock, patch

        from slopmop.cli.validate import _setup_dynamic_display
        from slopmop.core.executor import CheckExecutor
        from slopmop.core.result import CheckResult, CheckStatus
        from slopmop.reporting.console import ConsoleReporter

        executor = MagicMock(spec=CheckExecutor)
        reporter = MagicMock(spec=ConsoleReporter)

        with patch("slopmop.cli.validate.DynamicDisplay") as MockDisplay:
            mock_display = MagicMock()
            MockDisplay.return_value = mock_display
            _, deferred = _setup_dynamic_display(
                executor, reporter, quiet=True, project_root=tmp_path
            )

        # Extract the combined callback that was registered
        combined = executor.set_progress_callback.call_args[0][0]

        passed = CheckResult("check1", CheckStatus.PASSED, 0.1)
        failed = CheckResult("check2", CheckStatus.FAILED, 0.1)

        combined(passed)
        combined(failed)

        # Display receives all results
        assert mock_display.on_check_complete.call_count == 2
        # Failures are deferred (not sent to reporter immediately)
        reporter.on_check_complete.assert_not_called()
        assert len(deferred) == 1
        assert deferred[0] is failed


# ─── hooks edge cases ───────────────────────────────────────────────────


class TestHooksEdgeCases:
    """Edge-case coverage for hook install/status paths."""

    def test_status_hooks_dir_exists_but_empty(self, tmp_path, capsys):
        """When hooks dir exists but has no hook files → 'No commit hooks installed'."""
        (tmp_path / ".git" / "hooks").mkdir(parents=True)

        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="status",
        )
        result = cmd_commit_hooks(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "No commit hooks installed" in out

    def test_install_updates_existing_managed_hook(self, tmp_path, capsys):
        """Reinstalling over an existing sm-managed hook updates it."""
        (tmp_path / ".git" / "hooks").mkdir(parents=True)
        hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
        # Write an old managed hook
        hook_file.write_text(f"{SB_HOOK_MARKER}\n# Command: sm swab\nsm swab")
        hook_file.chmod(0o755)

        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="install",
            hook_verb="scour",
        )
        result = cmd_commit_hooks(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "Updating existing slopmop hook" in out
        # New hook should contain the new verb
        assert "sm scour" in hook_file.read_text()


# ─── validate edge cases ────────────────────────────────────────────────


class TestValidateSmLockError:
    """Tests for SmLockError handling in _run_validation."""

    @patch("slopmop.cli.validate.sm_lock")
    def test_lock_error_returns_1(self, mock_lock, tmp_path, capsys):
        from slopmop.cli.validate import _run_validation

        mock_lock.side_effect = __import__(
            "slopmop.core.lock", fromlist=["SmLockError"]
        ).SmLockError("Another sm instance is running")

        args = argparse.Namespace(
            project_root=str(tmp_path),
            quiet=False,
            verbose=False,
        )
        result = _run_validation(args, [], None)
        assert result == 1
        err = capsys.readouterr().err
        assert "Another sm instance" in err


class TestValidateJsonOutputFile:
    """Regression tests for JSON output-file behavior in validate pipeline."""

    @patch("builtins.print")
    @patch("slopmop.cli.validate.RunReport.from_summary")
    @patch("slopmop.cli.validate.JsonAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    def test_json_output_file_does_not_print_to_stdout(
        self,
        _mock_config,
        _mock_registry,
        mock_executor_cls,
        _mock_reporter,
        mock_json_adapter,
        mock_from_summary,
        mock_print,
        tmp_path,
    ):
        """--json with --output-file writes payload to file without stdout leak."""
        from slopmop.cli.validate import _run_validation

        mock_executor = MagicMock()
        mock_executor.run_checks.return_value = MagicMock(all_passed=True)
        mock_executor_cls.return_value = mock_executor

        mock_report = MagicMock()
        mock_from_summary.return_value = mock_report
        mock_json_adapter.render.return_value = {"ok": True}

        output_file = tmp_path / "result.json"
        args = argparse.Namespace(
            project_root=str(tmp_path),
            quiet=True,
            verbose=False,
            no_fail_fast=False,
            no_auto_fix=True,
            static=True,
            clear_history=False,
            swabbing_time=None,
            json_output=True,
            output_file=str(output_file),
            sarif_output=False,
            no_cache=False,
        )

        result = _run_validation(args, ["gate1"], "swab")

        assert result == 0
        assert output_file.exists()
        assert output_file.read_text(encoding="utf-8") == '{"ok":true}'
        mock_print.assert_not_called()
