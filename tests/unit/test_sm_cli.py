"""Tests for sb.py CLI functions.

Tests the CLI parser, command handlers, and helper functions.
"""

import argparse
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from slopmop.sm import (
    _generate_hook_script,
    _get_git_hooks_dir,
    _parse_hook_info,
    cmd_ci,
    cmd_commit_hooks,
    cmd_config,
    cmd_help,
    create_parser,
    detect_project_type,
    load_config,
    main,
    prompt_user,
    prompt_yes_no,
    setup_logging,
)


class TestLoadConfig:
    """Tests for load_config function."""

    def test_loads_config_from_file(self, tmp_path):
        """Config is loaded from .sb_config.json."""
        config = {"python": {"enabled": True}}
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
        assert parser.prog == "sb"

    def test_validate_subcommand(self):
        """Validate subcommand parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["validate", "commit"])
        assert args.verb == "validate"
        assert args.profile == "commit"

    def test_validate_with_quality_gates(self):
        """Validate with --quality-gates parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["validate", "-g", "python:tests", "python:coverage"])
        assert args.verb == "validate"
        assert args.quality_gates == ["python:tests", "python:coverage"]

    def test_validate_self_flag(self):
        """Validate --self flag parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["validate", "--self"])
        assert args.verb == "validate"
        assert args.self_validate is True

    def test_config_subcommand(self):
        """Config subcommand parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["config", "--show"])
        assert args.verb == "config"
        assert args.show is True

    def test_config_enable(self):
        """Config --enable parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["config", "--enable", "python-security"])
        assert args.verb == "config"
        assert args.enable == "python-security"

    def test_help_subcommand(self):
        """Help subcommand parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["help", "python-lint-format"])
        assert args.verb == "help"
        assert args.gate == "python-lint-format"

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
        args = parser.parse_args(["commit-hooks", "install", "commit"])
        assert args.verb == "commit-hooks"
        assert args.hooks_action == "install"
        assert args.profile == "commit"

    def test_commit_hooks_uninstall(self):
        """Commit-hooks uninstall parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["commit-hooks", "uninstall"])
        assert args.verb == "commit-hooks"
        assert args.hooks_action == "uninstall"


class TestDetectProjectType:
    """Tests for detect_project_type function."""

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

    def test_detects_test_directories(self, tmp_path):
        """Detects test directories."""
        (tmp_path / "tests").mkdir()
        result = detect_project_type(tmp_path)
        assert result["has_tests_dir"] is True
        assert "tests" in result["test_dirs"]

    def test_recommends_python_profile(self, tmp_path):
        """Recommends python profile for Python-only projects."""
        (tmp_path / "setup.py").write_text("")
        result = detect_project_type(tmp_path)
        assert result["recommended_profile"] == "python"

    def test_recommends_pr_profile_for_mixed(self, tmp_path):
        """Recommends pr profile for mixed Python/JS projects."""
        (tmp_path / "setup.py").write_text("")
        (tmp_path / "package.json").write_text("{}")
        result = detect_project_type(tmp_path)
        assert result["recommended_profile"] == "pr"

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
        """TypeScript projects recommend javascript-types gate."""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        result = detect_project_type(tmp_path)
        assert "javascript-types" in result["recommended_gates"]


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
        config = {"python": {"enabled": True}}
        (tmp_path / ".sb_config.json").write_text(json.dumps(config))

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=True,
            enable=None,
            disable=None,
            json=None,
        )

        with patch("slopmop.sm.ensure_checks_registered"):
            with patch("slopmop.sm.get_registry") as mock_registry:
                mock_reg = MagicMock()
                mock_reg.list_checks.return_value = ["python:tests"]
                mock_reg.get_definition.return_value = MagicMock(name="Python Tests")
                mock_reg.list_aliases.return_value = {"commit": ["python:tests"]}
                mock_registry.return_value = mock_reg

                result = cmd_config(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Configuration" in captured.out

    def test_enable_gate(self, tmp_path):
        """--enable adds gate to enabled list."""
        (tmp_path / ".sb_config.json").write_text(
            json.dumps({"disabled_gates": ["python-security"]})
        )

        args = argparse.Namespace(
            project_root=str(tmp_path),
            show=False,
            enable="python-security",
            disable=None,
            json=None,
        )

        with patch("slopmop.sm.ensure_checks_registered"):
            result = cmd_config(args)

        assert result == 0
        config = json.loads((tmp_path / ".sb_config.json").read_text())
        assert "python-security" not in config.get("disabled_gates", [])


class TestCmdHelp:
    """Tests for cmd_help command handler."""

    def test_help_all_gates(self, capsys):
        """Help without gate shows all gates."""
        args = argparse.Namespace(gate=None)

        with patch("slopmop.sm.ensure_checks_registered"):
            with patch("slopmop.sm.get_registry") as mock_registry:
                mock_reg = MagicMock()
                mock_reg.list_checks.return_value = ["python:tests", "python:coverage"]
                mock_reg.get_definition.return_value = MagicMock(
                    name="Test", auto_fix=False
                )
                mock_reg.list_aliases.return_value = {"commit": ["python:tests"]}
                mock_registry.return_value = mock_reg

                result = cmd_help(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Quality Gates" in captured.out

    def test_help_specific_gate(self, capsys):
        """Help for specific gate shows details."""
        args = argparse.Namespace(gate="python:tests")

        mock_check = MagicMock()
        mock_check.__doc__ = "Test documentation"

        with patch("slopmop.sm.ensure_checks_registered"):
            with patch("slopmop.sm.get_registry") as mock_registry:
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

    def test_help_alias(self, capsys):
        """Help for alias shows expanded gates."""
        args = argparse.Namespace(gate="commit")

        with patch("slopmop.sm.ensure_checks_registered"):
            with patch("slopmop.sm.get_registry") as mock_registry:
                mock_reg = MagicMock()
                mock_reg.get_definition.return_value = None
                mock_reg.is_alias.return_value = True
                mock_reg.expand_alias.return_value = ["python:tests", "python:coverage"]
                mock_registry.return_value = mock_reg

                result = cmd_help(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Profile: commit" in captured.out


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
        """Generates valid hook script."""
        script = _generate_hook_script("commit")
        assert "sm validate commit" in script
        assert "MANAGED BY SLOPBUCKET" in script

    def test_parse_hook_info_managed(self):
        """Parses managed hook info."""
        content = """# MANAGED BY SLOPBUCKET - DO NOT EDIT
#!/bin/sh
# Profile: commit
sm validate commit
"""
        result = _parse_hook_info(content)
        assert result is not None
        assert result["profile"] == "commit"
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
        """Install creates hook file."""
        (tmp_path / ".git").mkdir()

        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="install",
            profile="commit",
        )

        result = cmd_commit_hooks(args)

        assert result == 0
        hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
        assert hook_file.exists()
        assert "sm validate commit" in hook_file.read_text()

    def test_uninstall_hook(self, tmp_path, capsys):
        """Uninstall removes managed hooks."""
        (tmp_path / ".git" / "hooks").mkdir(parents=True)
        hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
        hook_file.write_text("# MANAGED BY SLOPBUCKET - DO NOT EDIT\nsm validate")

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

    def test_main_validate_calls_cmd_validate(self):
        """Main routes validate to cmd_validate."""
        with patch("slopmop.sm.cmd_validate") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["validate", "commit"])
            mock_cmd.assert_called_once()
            assert result == 0

    def test_main_config_calls_cmd_config(self):
        """Main routes config to cmd_config."""
        with patch("slopmop.sm.cmd_config") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["config", "--show"])
            mock_cmd.assert_called_once()
            assert result == 0

    def test_main_help_calls_cmd_help(self):
        """Main routes help to cmd_help."""
        with patch("slopmop.sm.cmd_help") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["help"])
            mock_cmd.assert_called_once()
            assert result == 0

    def test_main_commit_hooks_calls_cmd_commit_hooks(self):
        """Main routes commit-hooks to cmd_commit_hooks."""
        with patch("slopmop.sm.cmd_commit_hooks") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["commit-hooks", "status"])
            mock_cmd.assert_called_once()
            assert result == 0

    def test_main_ci_calls_cmd_ci(self):
        """Main routes ci to cmd_ci."""
        with patch("slopmop.sm.cmd_ci") as mock_cmd:
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
