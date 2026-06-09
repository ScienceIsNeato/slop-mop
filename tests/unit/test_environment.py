"""Tests for agent/TTY detection and the CLI flag-respect behavior wired to it.

Covers slopmop.utils.environment plus the auto-detect blocks in validate/buff/
refit that must respect an explicit --json / --no-json over agent auto-detection.
"""

import argparse
from unittest import mock

import pytest

from slopmop.utils.environment import is_agent_environment, is_interactive_terminal

_ENV_VARS = [
    "CI",
    "GEMINI_CLI",
    "CLAUDE_CODE",
    "AGENT_MODE",
    "TERM_PROGRAM",
    "NO_COLOR",
    "SLOPMOP_SAIL_VERBOSE",
]


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every marker env var so detection starts from a known baseline."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


class TestIsAgentEnvironment:
    def test_clean_env_is_not_agent(self, clean_env):
        assert is_agent_environment() is False

    @pytest.mark.parametrize("var", ["CI", "GEMINI_CLI", "CLAUDE_CODE", "AGENT_MODE"])
    def test_marker_env_vars_detected(self, clean_env, var):
        clean_env.setenv(var, "1")
        assert is_agent_environment() is True

    @pytest.mark.parametrize("term", ["Gemini", "ClaudeCode"])
    def test_term_program_agents_detected(self, clean_env, term):
        clean_env.setenv("TERM_PROGRAM", term)
        assert is_agent_environment() is True

    def test_unrelated_term_program_is_not_agent(self, clean_env):
        clean_env.setenv("TERM_PROGRAM", "iTerm.app")
        assert is_agent_environment() is False


class TestIsInteractiveTerminal:
    def test_non_tty_is_not_interactive(self, clean_env):
        with mock.patch("sys.stdout.isatty", return_value=False):
            assert is_interactive_terminal() is False

    def test_tty_clean_env_is_interactive(self, clean_env):
        with mock.patch("sys.stdout.isatty", return_value=True):
            assert is_interactive_terminal() is True

    def test_tty_but_agent_is_not_interactive(self, clean_env):
        clean_env.setenv("CI", "1")
        with mock.patch("sys.stdout.isatty", return_value=True):
            assert is_interactive_terminal() is False

    def test_tty_but_no_color_is_not_interactive(self, clean_env):
        clean_env.setenv("NO_COLOR", "1")
        with mock.patch("sys.stdout.isatty", return_value=True):
            assert is_interactive_terminal() is False

    def test_empty_no_color_still_disables_interactive(self, clean_env):
        # NO_COLOR spec: present at any value (incl. "") disables color.
        clean_env.setenv("NO_COLOR", "")
        with mock.patch("sys.stdout.isatty", return_value=True):
            assert is_interactive_terminal() is False


def _ns(**kw: object) -> argparse.Namespace:
    return argparse.Namespace(**kw)


class TestValidateModeHelpers:
    def test_json_mode_explicit_true(self, clean_env):
        from slopmop.cli.validate import _is_json_mode

        assert _is_json_mode(_ns(json_output=True)) is True

    def test_json_mode_explicit_false(self, clean_env):
        from slopmop.cli.validate import _is_json_mode

        assert _is_json_mode(_ns(json_output=False)) is False

    def test_json_mode_unset_defaults_false(self, clean_env):
        from slopmop.cli.validate import _is_json_mode

        assert _is_json_mode(_ns(json_output=None)) is False

    def test_porcelain_explicit_flag_wins(self, clean_env):
        from slopmop.cli.validate import _is_porcelain_mode

        assert _is_porcelain_mode(_ns(porcelain=True, json_output=None)) is True

    def test_porcelain_respects_explicit_no_json(self, clean_env):
        from slopmop.cli.validate import _is_porcelain_mode

        clean_env.setenv("CI", "1")  # agent env would otherwise auto-enable
        assert _is_porcelain_mode(_ns(porcelain=False, json_output=False)) is False

    def test_porcelain_respects_explicit_json(self, clean_env):
        from slopmop.cli.validate import _is_porcelain_mode

        clean_env.setenv("CI", "1")
        assert _is_porcelain_mode(_ns(porcelain=False, json_output=True)) is False

    def test_porcelain_auto_enables_for_agent_when_unset(self, clean_env):
        from slopmop.cli.validate import _is_porcelain_mode

        clean_env.setenv("CI", "1")
        assert _is_porcelain_mode(_ns(porcelain=False, json_output=None)) is True

    def test_porcelain_off_for_human_when_unset(self, clean_env):
        from slopmop.cli.validate import _is_porcelain_mode

        assert _is_porcelain_mode(_ns(porcelain=False, json_output=None)) is False


class TestRefitAutoDetect:
    def test_auto_enables_json_for_agent_when_unset(self, clean_env):
        from slopmop.cli import refit

        args = _ns(json_output=None)
        with (
            mock.patch(
                "slopmop.utils.environment.is_agent_environment", return_value=True
            ),
            mock.patch.object(
                refit, "_validate_start_review_args", return_value="stop"
            ),
        ):
            assert refit.cmd_refit(args) == 1
        assert args.json_output is True

    def test_respects_explicit_no_json(self, clean_env):
        from slopmop.cli import refit

        args = _ns(json_output=False)
        with (
            mock.patch(
                "slopmop.utils.environment.is_agent_environment", return_value=True
            ),
            mock.patch.object(
                refit, "_validate_start_review_args", return_value="stop"
            ),
        ):
            refit.cmd_refit(args)
        assert args.json_output is False


class TestBuffAutoDetect:
    def test_auto_enables_json_for_agent_when_unset(self, clean_env):
        from slopmop.cli import buff

        args = _ns(json_output=None, pr_or_action="x")
        with (
            mock.patch(
                "slopmop.utils.environment.is_agent_environment", return_value=True
            ),
            mock.patch.object(
                buff, "_normalize_buff_args", side_effect=ValueError("stop")
            ),
        ):
            assert buff.cmd_buff(args) == 2
        assert args.json_output is True

    def test_respects_explicit_no_json(self, clean_env):
        from slopmop.cli import buff

        args = _ns(json_output=False, pr_or_action="x")
        with (
            mock.patch(
                "slopmop.utils.environment.is_agent_environment", return_value=True
            ),
            mock.patch.object(
                buff, "_normalize_buff_args", side_effect=ValueError("stop")
            ),
        ):
            buff.cmd_buff(args)
        assert args.json_output is False


class TestSailPrintStep:
    def test_decorative_step_skipped_in_agent_env(self, clean_env, capsys):
        from slopmop.cli.sail import _print_step

        clean_env.setenv("CI", "1")
        _print_step("🧹", "Running swab", "checking gates")
        assert capsys.readouterr().out == ""

    def test_forced_step_prints_in_agent_env(self, clean_env, capsys):
        from slopmop.cli.sail import _print_step

        clean_env.setenv("CI", "1")
        _print_step("⚓", "HOLD", "address feedback", force=True)
        assert "HOLD" in capsys.readouterr().out

    def test_step_prints_for_human(self, clean_env, capsys):
        from slopmop.cli.sail import _print_step

        _print_step("🧹", "Running swab", "checking gates")
        assert "Running swab" in capsys.readouterr().out
