"""Tests for the status CLI command.

Tests the parser, dispatch, gate inventory, config summary,
hook status, and init integration — all without gate execution.
"""

import argparse
import json
from unittest.mock import MagicMock, patch

from slopmop.cli.status import (
    _find_other_aliases,
    _format_gate_line,
    _print_config_summary,
    _print_gate_inventory,
    _print_hooks_status,
    _print_recent_history,
    cmd_status,
    run_status,
)
from slopmop.reporting.timings import TimingStats
from slopmop.sm import create_parser, main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_registry(all_gates=None, swab_gates=None, scour_gates=None):
    """Build a mock registry for status tests."""
    mock_reg = MagicMock()
    mock_reg.list_checks.return_value = all_gates or []
    mock_reg.list_aliases.return_value = {}

    def _gate_names_for_level(level):
        from slopmop.checks.base import GateLevel

        if level == GateLevel.SWAB:
            return swab_gates or all_gates or []
        return scour_gates or all_gates or []

    mock_reg.get_gate_names_for_level.side_effect = _gate_names_for_level

    mock_check = MagicMock()
    mock_check.is_applicable.return_value = True
    mock_check.skip_reason.return_value = ""
    mock_reg.get_check.return_value = mock_check
    return mock_reg


def _stats(
    samples=(1.0, 1.1, 1.2),
    results=("passed", "passed", "passed"),
) -> TimingStats:
    """Build a TimingStats with defaults."""
    import statistics

    sorted_s = sorted(samples)
    med = statistics.median(sorted_s)
    n = len(sorted_s)
    if n < 2:
        q1_val = med
        q3_val = med
    else:
        mid = n // 2
        lower = sorted_s[:mid]
        upper = sorted_s[mid:] if n % 2 == 0 else sorted_s[mid + 1 :]
        q1_val = statistics.median(lower) if lower else med
        q3_val = statistics.median(upper) if upper else med
    return TimingStats(
        median=med,
        q1=q1_val,
        q3=q3_val,
        iqr=q3_val - q1_val,
        historical_max=max(samples),
        sample_count=len(samples),
        samples=tuple(samples),
        results=tuple(results),
    )


# ---------------------------------------------------------------------------
# Parser / dispatch
# ---------------------------------------------------------------------------


class TestStatusParser:
    """Tests for status subcommand argument parsing."""

    def test_status_parses(self):
        """Status subcommand parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["status"])
        assert args.verb == "status"

    def test_status_no_level_positional(self):
        """Status no longer has a level positional arg."""
        parser = create_parser()
        args = parser.parse_args(["status"])
        assert not hasattr(args, "level")

    def test_status_with_verbose(self):
        """Status --verbose flag parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["status", "--verbose"])
        assert args.verb == "status"
        assert args.verbose is True

    def test_status_with_quiet(self):
        """Status --quiet flag parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["status", "--quiet"])
        assert args.verb == "status"
        assert args.quiet is True

    def test_status_with_project_root(self, tmp_path):
        """Status --project-root parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["status", "--project-root", str(tmp_path)])
        assert args.verb == "status"
        assert args.project_root == str(tmp_path)

    def test_status_no_static_flag(self):
        """Status no longer has --static flag."""
        parser = create_parser()
        args = parser.parse_args(["status"])
        assert not hasattr(args, "static")


class TestMainDispatch:
    """Tests for main() routing to cmd_status."""

    def test_main_status_calls_cmd_status(self):
        """Main routes status to cmd_status."""
        with patch("slopmop.cli.cmd_status") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["status"])
            mock_cmd.assert_called_once()
            assert result == 0


# ---------------------------------------------------------------------------
# cmd_status / run_status wiring
# ---------------------------------------------------------------------------


class TestCmdStatus:
    """Tests for cmd_status command handler."""

    def _run(self, tmp_path, **ns_overrides):
        """Helper: run cmd_status with standard mocks."""
        (tmp_path / ".sb_config.json").write_text(json.dumps({}))
        ns = dict(
            project_root=str(tmp_path),
            verbose=False,
            quiet=True,
        )
        ns.update(ns_overrides)
        args = argparse.Namespace(**ns)
        registry = _mock_registry()
        with (
            patch(
                "slopmop.cli.status.get_registry",
                return_value=registry,
            ),
            patch("slopmop.cli.status.load_timings", return_value={}),
        ):
            result = cmd_status(args)
        return result, registry

    def test_always_returns_0(self, tmp_path):
        """Status is an observatory — always returns 0."""
        result, _ = self._run(tmp_path)
        assert result == 0

    def test_invalid_project_root(self, tmp_path, capsys):
        """Returns 1 for non-existent project root."""
        args = argparse.Namespace(
            project_root=str(tmp_path / "nonexistent"),
            verbose=False,
            quiet=False,
        )
        result = cmd_status(args)
        assert result == 1
        assert "not found" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _find_other_aliases helper
# ---------------------------------------------------------------------------


class TestFindOtherAliases:
    """Tests for _find_other_aliases helper."""

    def test_finds_matching_aliases(self):
        """Returns aliases that include the gate."""
        aliases = {
            "python": [
                "overconfidence:untested-code.py",
                "laziness:sloppy-formatting.py",
            ],
            "quality": [
                "overconfidence:untested-code.py",
                "laziness:complexity-creep.py",
            ],
            "quick": ["laziness:sloppy-formatting.py"],
        }
        result = _find_other_aliases(
            "overconfidence:untested-code.py", aliases, "python"
        )
        assert result == ["quality"]

    def test_excludes_current_level(self):
        """Does not include the current level."""
        aliases = {
            "python": ["overconfidence:untested-code.py"],
            "quality": ["overconfidence:untested-code.py"],
        }
        result = _find_other_aliases(
            "overconfidence:untested-code.py", aliases, "python"
        )
        assert "python" not in result

    def test_returns_empty_for_unique_gate(self):
        """Returns empty list if gate only in current alias."""
        aliases = {
            "python": ["overconfidence:untested-code.py"],
            "quality": ["laziness:complexity-creep.py"],
        }
        result = _find_other_aliases(
            "overconfidence:untested-code.py", aliases, "python"
        )
        assert result == []


# ---------------------------------------------------------------------------
# Gate line formatting
# ---------------------------------------------------------------------------


class TestFormatGateLine:
    """Tests for _format_gate_line output."""

    def test_not_applicable(self):
        """n/a gate shows skip reason."""
        line = _format_gate_line(
            "untested-code.js",
            in_swab=True,
            in_scour=False,
            is_applicable=False,
            skip_reason="No JavaScript code detected",
            history=None,
            colors_enabled=False,
        )
        assert "n/a" in line
        assert "No JavaScript code detected" in line

    def test_with_history_passed(self):
        """Gate with passing history shows last result."""
        stats = _stats(results=("passed", "passed", "failed", "passed"))
        line = _format_gate_line(
            "untested-code.py",
            in_swab=True,
            in_scour=False,
            is_applicable=True,
            skip_reason="",
            history=stats,
            colors_enabled=False,
        )
        assert "passed" in line
        assert "swab" in line

    def test_with_history_failed(self):
        """Gate with failing history shows failed."""
        stats = _stats(results=("passed", "failed"))
        line = _format_gate_line(
            "coverage-gaps.py",
            in_swab=True,
            in_scour=False,
            is_applicable=True,
            skip_reason="",
            history=stats,
            colors_enabled=False,
        )
        assert "failed" in line

    def test_no_history(self):
        """Gate with no history shows 'no history'."""
        line = _format_gate_line(
            "untested-code.py",
            in_swab=True,
            in_scour=False,
            is_applicable=True,
            skip_reason="",
            history=None,
            colors_enabled=False,
        )
        assert "no history" in line

    def test_scour_only_tag(self):
        """Gate only in scour shows scour tag."""
        line = _format_gate_line(
            "ignored-feedback",
            in_swab=False,
            in_scour=True,
            is_applicable=True,
            skip_reason="",
            history=None,
            colors_enabled=False,
        )
        assert "scour" in line


# ---------------------------------------------------------------------------
# Gate inventory output
# ---------------------------------------------------------------------------


class TestPrintGateInventory:
    """Tests for _print_gate_inventory output formatting."""

    def test_shows_category_header(self, capsys):
        """Inventory groups gates under category headers."""
        _print_gate_inventory(
            all_gates=["overconfidence:untested-code.py"],
            swab_gates={"overconfidence:untested-code.py"},
            scour_gates={"overconfidence:untested-code.py"},
            applicability={"overconfidence:untested-code.py": (True, "")},
            history={},
            colors_enabled=False,
        )
        out = capsys.readouterr().out
        assert "Overconfidence" in out

    def test_inventory_header(self, capsys):
        """Inventory section has GATE INVENTORY header."""
        _print_gate_inventory(
            all_gates=["overconfidence:untested-code.py"],
            swab_gates={"overconfidence:untested-code.py"},
            scour_gates={"overconfidence:untested-code.py"},
            applicability={"overconfidence:untested-code.py": (True, "")},
            history={},
            colors_enabled=False,
        )
        out = capsys.readouterr().out
        assert "GATE INVENTORY" in out

    def test_not_applicable_gate(self, capsys):
        """Not applicable gate shows reason."""
        _print_gate_inventory(
            all_gates=["overconfidence:untested-code.js"],
            swab_gates={"overconfidence:untested-code.js"},
            scour_gates={"overconfidence:untested-code.js"},
            applicability={
                "overconfidence:untested-code.js": (
                    False,
                    "No JavaScript code detected",
                )
            },
            history={},
            colors_enabled=False,
        )
        out = capsys.readouterr().out
        assert "n/a" in out
        assert "No JavaScript code detected" in out

    def test_gate_with_history(self, capsys):
        """Gate with history shows last result and sparkline."""
        history = {
            "overconfidence:untested-code.py": _stats(
                samples=(1.0, 1.1, 1.2),
                results=("passed", "passed", "passed"),
            )
        }
        _print_gate_inventory(
            all_gates=["overconfidence:untested-code.py"],
            swab_gates={"overconfidence:untested-code.py"},
            scour_gates={"overconfidence:untested-code.py"},
            applicability={"overconfidence:untested-code.py": (True, "")},
            history=history,
            colors_enabled=False,
        )
        out = capsys.readouterr().out
        assert "passed" in out

    def test_multiple_categories_sorted(self, capsys):
        """Gates are grouped by category in defined order."""
        _print_gate_inventory(
            all_gates=[
                "laziness:sloppy-formatting.py",
                "overconfidence:untested-code.py",
            ],
            swab_gates={
                "laziness:sloppy-formatting.py",
                "overconfidence:untested-code.py",
            },
            scour_gates={
                "laziness:sloppy-formatting.py",
                "overconfidence:untested-code.py",
            },
            applicability={
                "laziness:sloppy-formatting.py": (True, ""),
                "overconfidence:untested-code.py": (True, ""),
            },
            history={},
            colors_enabled=False,
        )
        out = capsys.readouterr().out
        # Overconfidence should appear before Laziness
        over_pos = out.index("Overconfidence")
        lazy_pos = out.index("Laziness")
        assert over_pos < lazy_pos


# ---------------------------------------------------------------------------
# Config summary
# ---------------------------------------------------------------------------


class TestPrintConfigSummary:
    """Tests for _print_config_summary output."""

    def test_shows_gate_counts(self, capsys, tmp_path):
        """Shows swab and scour gate counts."""
        (tmp_path / ".sb_config.json").write_text("{}")
        _print_config_summary(tmp_path, {}, swab_count=15, scour_count=5, disabled=[])
        out = capsys.readouterr().out
        assert "15 swab" in out
        assert "5 scour" in out

    def test_shows_time_budget(self, capsys, tmp_path):
        """Shows swabbing-time budget when configured."""
        _print_config_summary(
            tmp_path,
            {"swabbing_time": 30},
            swab_count=10,
            scour_count=3,
            disabled=[],
        )
        out = capsys.readouterr().out
        assert "30s" in out

    def test_shows_disabled_gates(self, capsys, tmp_path):
        """Shows disabled gate count and names."""
        _print_config_summary(
            tmp_path,
            {},
            swab_count=10,
            scour_count=3,
            disabled=["overconfidence:untested-code.py"],
        )
        out = capsys.readouterr().out
        assert "Disabled" in out
        assert "untested-code.py" in out

    def test_shows_config_file(self, capsys, tmp_path):
        """Shows config file path when it exists."""
        (tmp_path / ".sb_config.json").write_text("{}")
        _print_config_summary(tmp_path, {}, swab_count=5, scour_count=2, disabled=[])
        out = capsys.readouterr().out
        assert ".sb_config.json" in out


# ---------------------------------------------------------------------------
# Hook status
# ---------------------------------------------------------------------------


class TestPrintHooksStatus:
    """Tests for _print_hooks_status output."""

    def test_no_hooks_dir(self, capsys, tmp_path):
        """Shows message when no hooks directory exists."""
        (tmp_path / ".git").mkdir()
        _print_hooks_status(tmp_path)
        out = capsys.readouterr().out
        assert "No hooks directory found" in out

    def test_sm_hook_found(self, capsys, tmp_path):
        """Shows sm-managed hook with verb."""
        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        hook = hooks_dir / "pre-commit"
        hook.write_text("#!/bin/sh\n# MANAGED BY SLOP-MOP\nsm swab\n")
        _print_hooks_status(tmp_path)
        out = capsys.readouterr().out
        assert "pre-commit" in out
        assert "swab" in out

    def test_non_sm_hook_found(self, capsys, tmp_path):
        """Shows non-sm hooks separately."""
        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        hook = hooks_dir / "pre-commit"
        hook.write_text("#!/bin/sh\necho hello\n")
        _print_hooks_status(tmp_path)
        out = capsys.readouterr().out
        assert "non-sm hook" in out

    def test_no_hooks_installed(self, capsys, tmp_path):
        """Shows message when hooks dir exists but no hooks."""
        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        _print_hooks_status(tmp_path)
        out = capsys.readouterr().out
        assert "No hooks installed" in out


# ---------------------------------------------------------------------------
# Recent history
# ---------------------------------------------------------------------------


class TestPrintRecentHistory:
    """Tests for _print_recent_history output."""

    def test_no_history(self, capsys):
        """Shows prompt to run swab when no history."""
        _print_recent_history({})
        out = capsys.readouterr().out
        assert "No gate run history found" in out

    def test_with_history(self, capsys):
        """Shows last-known status counts."""
        history = {
            "overconfidence:untested-code.py": _stats(results=("passed", "passed")),
            "overconfidence:coverage-gaps.py": _stats(results=("failed",)),
        }
        _print_recent_history(history)
        out = capsys.readouterr().out
        assert "1 failed" in out
        assert "1 passed" in out
        assert "2 gates tracked" in out


# ---------------------------------------------------------------------------
# run_status direct invocation
# ---------------------------------------------------------------------------


class TestRunStatus:
    """Tests for the run_status() function called directly."""

    def _run(self, tmp_path):
        """Helper: call run_status with standard mocks."""
        (tmp_path / ".sb_config.json").write_text(json.dumps({}))
        registry = _mock_registry()
        with (
            patch("slopmop.cli.status.get_registry", return_value=registry),
            patch("slopmop.cli.status.load_timings", return_value={}),
        ):
            result = run_status(project_root=str(tmp_path))
        return result, registry

    def test_always_returns_0(self, tmp_path):
        """run_status always returns 0 (observatory)."""
        result, _ = self._run(tmp_path)
        assert result == 0

    def test_invalid_project_root(self, tmp_path, capsys):
        """run_status returns 1 for non-existent path."""
        result = run_status(project_root=str(tmp_path / "nonexistent"))
        assert result == 1
        assert "not found" in capsys.readouterr().out

    def test_shows_dashboard_header(self, tmp_path, capsys):
        """run_status shows dashboard header."""
        (tmp_path / ".sb_config.json").write_text(json.dumps({}))
        registry = _mock_registry()
        with (
            patch("slopmop.cli.status.get_registry", return_value=registry),
            patch("slopmop.cli.status.load_timings", return_value={}),
        ):
            run_status(project_root=str(tmp_path))
        out = capsys.readouterr().out
        assert "project dashboard" in out

    def test_no_executor_used(self, tmp_path):
        """run_status does NOT use CheckExecutor."""
        (tmp_path / ".sb_config.json").write_text(json.dumps({}))
        registry = _mock_registry()
        with (
            patch("slopmop.cli.status.get_registry", return_value=registry),
            patch("slopmop.cli.status.load_timings", return_value={}),
            patch("slopmop.core.executor.CheckExecutor", side_effect=AssertionError),
        ):
            # Should NOT raise — executor is never imported or used
            result = run_status(project_root=str(tmp_path))
            assert result == 0


# ---------------------------------------------------------------------------
# Init integration
# ---------------------------------------------------------------------------


class TestInitCallsStatus:
    """Tests that sm init runs status at the end."""

    def test_cmd_init_calls_run_status(self, tmp_path):
        """cmd_init calls run_status after writing config."""
        args = argparse.Namespace(
            project_root=str(tmp_path),
            config=None,
            non_interactive=True,
        )
        (tmp_path / "setup.py").write_text("")

        with patch("slopmop.cli.status.run_status") as mock_run_status:
            mock_run_status.return_value = 0
            from slopmop.cli.init import cmd_init

            result = cmd_init(args)

        assert result == 0
        mock_run_status.assert_called_once()
        call_kwargs = mock_run_status.call_args[1]
        assert call_kwargs["project_root"] == str(tmp_path)
