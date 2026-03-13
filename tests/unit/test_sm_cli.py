"""Tests for sb.py CLI functions.

Tests the CLI parser, command handlers, and helper functions.
"""

import argparse
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from slopmop.cli.buff import cmd_buff
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

    def test_buff_subcommand(self):
        """Buff subcommand parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["buff"])
        assert args.verb == "buff"

    def test_buff_with_pr_number(self):
        """Buff with explicit PR number parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["buff", "84"])
        assert args.verb == "buff"
        assert args.pr_or_action == "84"
        assert args.action_args == []

    def test_buff_inspect_parses(self):
        """Buff inspect parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["buff", "inspect", "84"])
        assert args.verb == "buff"
        assert args.pr_or_action == "inspect"
        assert args.action_args == ["84"]

    def test_buff_iterate_parses(self):
        """Buff iterate parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["buff", "iterate", "84"])
        assert args.verb == "buff"
        assert args.pr_or_action == "iterate"
        assert args.action_args == ["84"]

    def test_buff_finalize_parses(self):
        """Buff finalize parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["buff", "finalize", "84", "--push"])
        assert args.verb == "buff"
        assert args.pr_or_action == "finalize"
        assert args.action_args == ["84"]
        assert args.push is True

    def test_buff_status_parses(self):
        """Buff status parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["buff", "status", "84"])
        assert args.verb == "buff"
        assert args.pr_or_action == "status"
        assert args.action_args == ["84"]

    def test_buff_watch_parses(self):
        """Buff watch parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["buff", "watch", "84", "--interval", "10"])
        assert args.verb == "buff"
        assert args.pr_or_action == "watch"
        assert args.action_args == ["84"]
        assert args.interval == 10

    def test_buff_json_and_output_file_flags(self):
        """Buff supports JSON stdout and machine output file mirroring."""
        parser = create_parser()
        args = parser.parse_args(
            ["buff", "84", "--json", "--output-file", "triage.json"]
        )
        assert args.verb == "buff"
        assert args.pr_or_action == "84"
        assert args.action_args == []
        assert args.json_output is True
        assert args.output_file == "triage.json"

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

    def test_config_current_pr_number(self):
        """Config --current-pr-number parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["config", "--current-pr-number", "85"])
        assert args.verb == "config"
        assert args.current_pr_number == 85

    def test_config_clear_current_pr(self):
        """Config --clear-current-pr parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["config", "--clear-current-pr"])
        assert args.verb == "config"
        assert args.clear_current_pr is True

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

    def test_agent_install_parses(self):
        """Agent install subcommand parses correctly."""
        parser = create_parser()
        args = parser.parse_args(
            ["agent", "install", "--target", "cursor", "--project-root", "."]
        )
        assert args.verb == "agent"
        assert args.agent_action == "install"
        assert args.target == "cursor"
        assert args.project_root == "."

    def test_agent_install_parses_copilot_target(self):
        """Agent install accepts the copilot target."""
        parser = create_parser()
        args = parser.parse_args(["agent", "install", "--target", "copilot"])
        assert args.verb == "agent"
        assert args.agent_action == "install"
        assert args.target == "copilot"


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
        """Dart repos should get first-class Flutter gates, not custom shells."""
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
        assert result["suggested_custom_gates"] == []
        assert "laziness:flutter-analyze" in result["recommended_gates"]
        assert "overconfidence:flutter-test" in result["recommended_gates"]
        assert "laziness:dart-format-check" in result["recommended_gates"]
        assert "overconfidence:coverage-gaps.dart" in result["recommended_gates"]
        assert "deceptiveness:bogus-tests.dart" in result["recommended_gates"]
        assert "laziness:generated-artifacts.dart" in result["recommended_gates"]

    def test_dart_detection_omits_flutter_custom_gates_when_tools_missing(
        self, tmp_path
    ):
        """Dart still gets first-class recommendations and missing-tool mapping."""
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
        assert "laziness:flutter-analyze" in result["recommended_gates"]
        assert "overconfidence:flutter-test" in result["recommended_gates"]
        assert "laziness:dart-format-check" in result["recommended_gates"]
        assert "overconfidence:coverage-gaps.dart" in result["recommended_gates"]
        assert (
            "flutter",
            "laziness:flutter-analyze",
            "Install Flutter SDK: https://docs.flutter.dev/get-started/install",
        ) in result["missing_tools"]
        assert (
            "flutter",
            "overconfidence:flutter-test",
            "Install Flutter SDK: https://docs.flutter.dev/get-started/install",
        ) in result["missing_tools"]
        assert (
            "dart",
            "laziness:dart-format-check",
            "Install Dart SDK: https://dart.dev/get-dart",
        ) in result["missing_tools"]


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
        assert "--swabbing-time 0" in script
        assert "--json-file .slopmop/last_swab.json" in script
        assert "--json --output-file" not in script
        assert "Structured results:" in script
        assert "mkdir -p .slopmop" in script

    def test_generate_hook_script_direct_verb(self):
        """Generates hook script when given a verb directly."""
        script = _generate_hook_script("scour")
        assert "sm scour" in script
        assert "# Command: sm scour" in script
        assert "--swabbing-time 0" in script
        assert "--json-file .slopmop/last_scour.json" in script

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

    def test_main_buff_calls_cmd_buff(self):
        """Main routes buff to cmd_buff."""
        with patch("slopmop.cli.cmd_buff") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["buff"])
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

    def test_main_agent_calls_cmd_agent(self):
        """Main routes agent to cmd_agent."""
        with patch("slopmop.cli.cmd_agent") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["agent", "install"])
            mock_cmd.assert_called_once()
            assert result == 0


class TestBuffStatus:
    """Tests for CI status actions through cmd_buff."""

    @staticmethod
    def _make_args(pr_or_action: str, action_args=None, interval: int = 30):
        return argparse.Namespace(
            pr_or_action=pr_or_action,
            action_args=action_args or [],
            interval=interval,
        )

    def test_ci_no_pr_context(self, tmp_path):
        """Returns error when no PR context is available for buff status."""
        args = self._make_args("status")

        with patch("slopmop.cli.buff._detect_pr_number", return_value=None):
            result = cmd_buff(args)

        assert result == 2  # No PR context error

    def test_ci_with_explicit_pr_number(self, tmp_path, capsys):
        """Uses explicit PR number when provided via buff status."""
        args = self._make_args("status", ["42"])

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
            result = cmd_buff(args)

        captured = capsys.readouterr()
        assert result == 0
        assert "PR: #42" in captured.out
        assert "CI CLEAN" in captured.out

    def test_ci_with_failures(self, tmp_path, capsys):
        """Returns failure when checks fail via buff status."""
        args = self._make_args("status", ["1"])

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
            result = cmd_buff(args)

        captured = capsys.readouterr()
        assert result == 1
        assert "SLOP IN CI" in captured.out
        assert "failed-check" in captured.out

    def test_ci_in_progress_no_watch(self, tmp_path, capsys):
        """Returns exit code 1 with in-progress checks in buff status mode."""
        args = self._make_args("status", ["1"])

        checks_response = json.dumps(
            [
                {"name": "running-check", "state": "in_progress", "bucket": "pending"},
            ]
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=checks_response, stderr=""
            )
            result = cmd_buff(args)

        captured = capsys.readouterr()
        assert result == 1
        assert "CI IN PROGRESS" in captured.out
        assert "sm buff watch" in captured.out

    def test_ci_no_checks(self, tmp_path, capsys):
        """Returns success when no checks found."""
        args = self._make_args("status", ["1"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
            result = cmd_buff(args)

        captured = capsys.readouterr()
        assert result == 0
        assert "No CI checks found" in captured.out

    def test_ci_gh_not_found(self, tmp_path, capsys):
        """Returns error when gh CLI is not available."""
        args = self._make_args("status", ["1"])

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            result = cmd_buff(args)

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

    def test_json_mode_defaults_to_console(self):
        """Validation defaults to human-readable output unless --json is set."""
        from slopmop.cli.validate import _is_json_mode

        args = argparse.Namespace(json_output=None)
        assert _is_json_mode(args) is False

    @patch("builtins.print")
    @patch("slopmop.cli.validate.RunReport.from_summary")
    @patch("slopmop.cli.validate.JsonAdapter")
    @patch("slopmop.cli.validate.ConsoleReporter")
    @patch("slopmop.cli.validate.CheckExecutor")
    @patch("slopmop.cli.validate.get_registry")
    @patch("slopmop.sm.load_config", return_value={})
    def test_json_output_file_mirrors_and_prints_to_stdout(
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
        """--json with --output-file writes payload to file and stdout."""
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
        mock_print.assert_called_once_with('{"ok":true}')
