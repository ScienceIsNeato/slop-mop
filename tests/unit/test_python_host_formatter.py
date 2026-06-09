"""Tests for host-formatter detection and the sloppy-formatting.py ruff branch.

Covers:
  - detect_host_python_formatter() detection signals
  - PythonLintFormatCheck._effective_formatter() config override
  - auto_fix() dispatching to ruff vs black
  - run() using ruff format --check when ruff is detected
  - _BLACK_EXTEND_EXCLUDE presence in black calls (barnacle #263)
"""

from unittest.mock import MagicMock

from slopmop.checks.python._host_formatter import detect_host_python_formatter
from slopmop.checks.python.lint_format import (
    _BLACK_EXTEND_EXCLUDE,
    PythonLintFormatCheck,
)
from slopmop.core.result import CheckStatus
from slopmop.subprocess.runner import SubprocessResult

# ---------------------------------------------------------------------------
# detect_host_python_formatter
# ---------------------------------------------------------------------------


class TestDetectHostPythonFormatter:
    def test_no_config_returns_none(self, tmp_path):
        assert detect_host_python_formatter(str(tmp_path)) is None

    def test_tool_ruff_section_in_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nselect = ['E']\n")
        assert detect_host_python_formatter(str(tmp_path)) == "ruff"

    def test_tool_ruff_format_section_in_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "[tool.ruff.format]\nquote-style = 'double'\n"
        )
        assert detect_host_python_formatter(str(tmp_path)) == "ruff"

    def test_tool_ruff_lint_section_in_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "[tool.ruff.lint]\nselect = ['E', 'F']\n"
        )
        assert detect_host_python_formatter(str(tmp_path)) == "ruff"

    def test_tool_black_section_returns_black(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.black]\nline-length = 88\n")
        assert detect_host_python_formatter(str(tmp_path)) == "black"

    def test_ruff_takes_priority_over_black(self, tmp_path):
        # Both configured — ruff section appears first
        (tmp_path / "pyproject.toml").write_text(
            "[tool.ruff]\nselect = ['E']\n[tool.black]\nline-length = 88\n"
        )
        assert detect_host_python_formatter(str(tmp_path)) == "ruff"

    def test_dot_ruff_toml_returns_ruff(self, tmp_path):
        (tmp_path / ".ruff.toml").write_text("line-length = 88\n")
        assert detect_host_python_formatter(str(tmp_path)) == "ruff"

    def test_ruff_toml_returns_ruff(self, tmp_path):
        (tmp_path / "ruff.toml").write_text("line-length = 88\n")
        assert detect_host_python_formatter(str(tmp_path)) == "ruff"

    def test_precommit_with_ruff_hook(self, tmp_path):
        (tmp_path / ".pre-commit-config.yaml").write_text(
            "repos:\n"
            "  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
            "    hooks:\n"
            "      - id: ruff\n"
            "      - id: ruff-format\n"
        )
        assert detect_host_python_formatter(str(tmp_path)) == "ruff"

    def test_precommit_without_ruff_returns_none(self, tmp_path):
        (tmp_path / ".pre-commit-config.yaml").write_text(
            "repos:\n"
            "  - repo: https://github.com/psf/black\n"
            "    hooks:\n"
            "      - id: black\n"
        )
        # black via pre-commit alone doesn't return 'black' — no pyproject.toml
        assert detect_host_python_formatter(str(tmp_path)) is None

    def test_unreadable_pyproject_falls_through(self, tmp_path):
        # Can't chmod in a tmp_path test to make it unreadable portably,
        # but a malformed pyproject.toml should not crash detection.
        (tmp_path / "pyproject.toml").write_text("not valid toml [[[")
        # Should not raise; may return None or a value based on text match
        result = detect_host_python_formatter(str(tmp_path))
        assert result in (None, "ruff", "black")


# ---------------------------------------------------------------------------
# _effective_formatter() config override
# ---------------------------------------------------------------------------


class TestEffectiveFormatter:
    def test_auto_detects_ruff_from_project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
        check = PythonLintFormatCheck({})
        assert check._effective_formatter(str(tmp_path)) == "ruff"

    def test_auto_returns_none_when_nothing_configured(self, tmp_path):
        check = PythonLintFormatCheck({})
        assert check._effective_formatter(str(tmp_path)) is None

    def test_override_ruff_ignores_project(self, tmp_path):
        # No project config, but explicit override
        check = PythonLintFormatCheck({"formatter": "ruff"})
        assert check._effective_formatter(str(tmp_path)) == "ruff"

    def test_override_black_ignores_ruff_config(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
        check = PythonLintFormatCheck({"formatter": "black"})
        assert check._effective_formatter(str(tmp_path)) == "black"

    def test_override_none_returns_none_sentinel(self, tmp_path):
        check = PythonLintFormatCheck({"formatter": "none"})
        assert check._effective_formatter(str(tmp_path)) == "none"


# ---------------------------------------------------------------------------
# auto_fix() dispatching
# ---------------------------------------------------------------------------


class TestAutoFixDispatching:
    def _make_runner(self, success: bool = True) -> MagicMock:
        runner = MagicMock()
        runner.run.return_value = SubprocessResult(
            returncode=0 if success else 1,
            stdout="",
            stderr="",
            duration=0.1,
        )
        return runner

    def test_auto_fix_uses_ruff_when_detected(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
        runner = self._make_runner()
        check = PythonLintFormatCheck({}, runner=runner)
        check.auto_fix(str(tmp_path))

        calls = [c.args[0] for c in runner.run.call_args_list]
        # Executable path may be resolved (/usr/bin/ruff etc.)
        assert any("ruff" in c[0] for c in calls if c)
        assert not any("black" in c[0] for c in calls if c)

    def test_auto_fix_uses_black_when_no_ruff(self, tmp_path):
        runner = self._make_runner()
        check = PythonLintFormatCheck({}, runner=runner)
        check.auto_fix(str(tmp_path))

        calls = [c.args[0] for c in runner.run.call_args_list]
        assert any("black" in c[0] for c in calls if c)
        assert not any("ruff" in c[0] for c in calls if c)

    def test_auto_fix_skips_all_when_formatter_none(self, tmp_path):
        runner = self._make_runner()
        check = PythonLintFormatCheck({"formatter": "none"}, runner=runner)
        result = check.auto_fix(str(tmp_path))

        assert result is False
        runner.run.assert_not_called()

    def test_auto_fix_ruff_calls_format_and_check(self, tmp_path):
        runner = self._make_runner()
        check = PythonLintFormatCheck({"formatter": "ruff"}, runner=runner)
        check.auto_fix(str(tmp_path))

        calls = [c.args[0] for c in runner.run.call_args_list]
        ruff_cmds = [c for c in calls if c and "ruff" in c[0]]
        subcommands = [c[1] for c in ruff_cmds if len(c) > 1]
        assert "format" in subcommands
        assert "check" in subcommands

    def test_black_call_includes_extend_exclude(self, tmp_path):
        """Black must pass --extend-exclude to skip migration dirs (#263)."""
        runner = self._make_runner()
        check = PythonLintFormatCheck({"formatter": "black"}, runner=runner)
        check.auto_fix(str(tmp_path))

        calls = [c.args[0] for c in runner.run.call_args_list]
        black_calls = [c for c in calls if c and "black" in c[0]]
        assert black_calls, "black should have been called"
        for cmd in black_calls:
            assert (
                "--extend-exclude" in cmd
            ), "black must pass --extend-exclude to skip migration dirs"


# ---------------------------------------------------------------------------
# run() ruff branch
# ---------------------------------------------------------------------------


class TestRunRuffBranch:
    def _make_runner(self, returncode: int = 0) -> MagicMock:
        runner = MagicMock()
        runner.run.return_value = SubprocessResult(
            returncode=returncode, stdout="", stderr="", duration=0.1
        )
        return runner

    def test_run_uses_ruff_format_check_when_ruff_configured(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        runner = self._make_runner(returncode=0)
        check = PythonLintFormatCheck({}, runner=runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        calls = [c.args[0] for c in runner.run.call_args_list]
        ruff_format_check = [
            c
            for c in calls
            if c and "ruff" in c[0] and "format" in c and "--check" in c
        ]
        assert ruff_format_check, "ruff format --check should have been called"

    def test_run_uses_black_check_when_no_ruff(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        runner = self._make_runner(returncode=0)
        check = PythonLintFormatCheck({}, runner=runner)
        check.run(str(tmp_path))

        calls = [c.args[0] for c in runner.run.call_args_list]
        black_check = [c for c in calls if c and "black" in c[0] and "--check" in c]
        assert black_check, "black --check should have been called"

    def test_run_passes_when_formatter_none(self, tmp_path):
        check = PythonLintFormatCheck({"formatter": "none"})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED
        assert "none" in result.output.lower()

    def test_run_fails_when_ruff_format_fails(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").touch()

        runner = MagicMock()

        def side_effect(cmd, *args, **kwargs):
            if cmd and "ruff" in cmd[0] and "format" in cmd:
                return SubprocessResult(
                    returncode=1,
                    stdout="Would reformat src/main.py",
                    stderr="",
                    duration=0.1,
                )
            return SubprocessResult(returncode=0, stdout="", stderr="", duration=0.1)

        runner.run.side_effect = side_effect
        check = PythonLintFormatCheck({}, runner=runner)
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "ruff" in result.fix_suggestion.lower()


# ---------------------------------------------------------------------------
# _BLACK_EXTEND_EXCLUDE sanity
# ---------------------------------------------------------------------------


class TestBlackExtendExclude:
    def test_migrations_in_pattern(self):
        import re

        assert re.search(_BLACK_EXTEND_EXCLUDE, "/migrations/")

    def test_alembic_in_pattern(self):
        import re

        assert re.search(_BLACK_EXTEND_EXCLUDE, "/alembic/")

    def test_venv_in_pattern(self):
        import re

        assert re.search(_BLACK_EXTEND_EXCLUDE, "/venv/")

    def test_normal_source_not_excluded(self):
        import re

        assert not re.search(_BLACK_EXTEND_EXCLUDE, "/myapp/")
        assert not re.search(_BLACK_EXTEND_EXCLUDE, "/server/")
