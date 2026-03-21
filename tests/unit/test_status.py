"""Tests for the status CLI command.

Tests the parser, dispatch, gate inventory, config summary,
hook status, and init integration — all without gate execution.
"""

import argparse
import json
from unittest.mock import patch

from slopmop.cli.ci import _categorize_checks
from slopmop.cli.status import (
    _failure_counts_from_artifact,
    _format_gate_line,
    _gather_baseline_snapshot_data,
    _gather_ci_data,
    _gather_workflow_data,
    _load_latest_gate_results,
    _print_baseline_snapshot,
    _print_ci_summary,
    _print_config_summary,
    _print_gate_inventory,
    _print_hooks_status,
    _print_recent_history,
    _print_workflow_position,
    cmd_status,
)
from slopmop.reporting.timings import TimingStats
from slopmop.sm import create_parser, main
from tests.conftest import make_mock_status_registry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# _format_gate_line
# ---------------------------------------------------------------------------


class TestFormatGateLine:
    """Tests for _format_gate_line rendering."""

    def test_swab_gate_no_history(self):
        line = _format_gate_line(
            "sloppy-formatting.py",
            role="foundation",
            in_swab=True,
            in_scour=False,
            is_applicable=True,
            skip_reason="",
            history=None,
            colors_enabled=False,
        )
        assert "swab" in line
        assert "sloppy-formatting.py" in line
        assert "no history" in line

    def test_not_applicable_shows_skip_reason(self):
        line = _format_gate_line(
            "coverage-gaps.py",
            role="foundation",
            in_swab=True,
            in_scour=False,
            is_applicable=False,
            skip_reason="no pytest",
            history=None,
            colors_enabled=False,
        )
        assert "⊘" in line
        assert "no pytest" in line

    def test_with_history_shows_last_result(self):
        stats = _stats(results=("passed", "failed", "passed"))
        line = _format_gate_line(
            "bogus-tests.py",
            role="diagnostic",
            in_swab=True,
            in_scour=False,
            is_applicable=True,
            skip_reason="",
            history=stats,
            colors_enabled=False,
        )
        assert "last:" in line
        assert "passed" in line

    def test_scour_only_gate(self):
        line = _format_gate_line(
            "ignored-feedback",
            role="diagnostic",
            in_swab=False,
            in_scour=True,
            is_applicable=True,
            skip_reason="",
            history=None,
            colors_enabled=False,
        )
        assert "scour" in line

    def test_scour_only_no_history_shows_helpful_hint(self):
        line = _format_gate_line(
            "dependency-risk.py",
            role="foundation",
            in_swab=False,
            in_scour=True,
            is_applicable=True,
            skip_reason="",
            history=None,
            colors_enabled=False,
        )
        assert "run sm scour" in line

    def test_role_badge_included(self):
        line = _format_gate_line(
            "test-gate",
            role="foundation",
            in_swab=True,
            in_scour=False,
            is_applicable=True,
            skip_reason="",
            history=None,
            colors_enabled=False,
        )
        # Foundation role badge is "🔧 "
        assert "🔧" in line


# ---------------------------------------------------------------------------
# _print_config_summary
# ---------------------------------------------------------------------------


class TestPrintConfigSummary:
    """Tests for _print_config_summary output."""

    def test_prints_gate_counts(self, tmp_path, capsys):
        config = {}
        _print_config_summary(
            tmp_path, config, swab_count=5, scour_count=2, disabled=[]
        )
        captured = capsys.readouterr()
        assert "5 swab" in captured.out
        assert "2 scour" in captured.out

    def test_prints_disabled_gates(self, tmp_path, capsys):
        config = {}
        _print_config_summary(
            tmp_path,
            config,
            swab_count=3,
            scour_count=1,
            disabled=["laziness:sloppy-formatting.py"],
        )
        captured = capsys.readouterr()
        assert "1 gate(s)" in captured.out
        assert "sloppy-formatting.py" in captured.out

    def test_prints_time_budget(self, tmp_path, capsys):
        config = {"swabbing_time": 120}
        _print_config_summary(
            tmp_path, config, swab_count=3, scour_count=1, disabled=[]
        )
        captured = capsys.readouterr()
        assert "120s" in captured.out

    def test_shows_config_file_when_present(self, tmp_path, capsys):
        (tmp_path / ".sb_config.json").write_text("{}")
        config = {}
        _print_config_summary(
            tmp_path, config, swab_count=1, scour_count=0, disabled=[]
        )
        captured = capsys.readouterr()
        assert ".sb_config.json" in captured.out


# ---------------------------------------------------------------------------
# _print_hooks_status
# ---------------------------------------------------------------------------


class TestPrintHooksStatus:
    """Tests for _print_hooks_status output."""

    def test_no_git_dir(self, tmp_path, capsys):
        _print_hooks_status(tmp_path)
        captured = capsys.readouterr()
        assert "No hooks" in captured.out

    def test_sm_hook_detected(self, tmp_path, capsys):
        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        from slopmop.cli.hooks import SB_HOOK_MARKER

        hook_content = f"#!/bin/sh\n{SB_HOOK_MARKER}\nsm swab\n"
        (hooks_dir / "pre-commit").write_text(hook_content)
        _print_hooks_status(tmp_path)
        captured = capsys.readouterr()
        assert "✅" in captured.out
        assert "pre-commit" in captured.out


# ---------------------------------------------------------------------------
# _print_recent_history
# ---------------------------------------------------------------------------


class TestPrintRecentHistory:
    """Tests for _print_recent_history output."""

    def test_empty_history(self, capsys):
        _print_recent_history({})
        captured = capsys.readouterr()
        assert "No gate run history" in captured.out

    def test_with_history(self, capsys):
        history = {"overconfidence:untested-code.py": _stats()}
        _print_recent_history(history)
        captured = capsys.readouterr()
        assert "RECENT HISTORY" in captured.out

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
        registry = make_mock_status_registry()
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
# Gate line formatting
# ---------------------------------------------------------------------------


class TestFormatGateLine:
    """Tests for _format_gate_line output."""

    def test_not_applicable(self):
        """n/a gate shows skip reason."""
        line = _format_gate_line(
            "untested-code.js",
            role="foundation",
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
            role="foundation",
            in_swab=True,
            in_scour=False,
            is_applicable=True,
            skip_reason="",
            history=stats,
            colors_enabled=False,
        )
        assert "last:" in line
        assert "passed" in line
        assert "swab" in line

    def test_with_history_failed(self):
        """Gate with failing history shows failed."""
        stats = _stats(results=("passed", "failed"))
        line = _format_gate_line(
            "coverage-gaps.py",
            role="foundation",
            in_swab=True,
            in_scour=False,
            is_applicable=True,
            skip_reason="",
            history=stats,
            colors_enabled=False,
        )
        assert "last:" in line
        assert "failed" in line

    def test_no_history(self):
        """Gate with no history shows 'no history'."""
        line = _format_gate_line(
            "untested-code.py",
            role="foundation",
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
            role="diagnostic",
            in_swab=False,
            in_scour=True,
            is_applicable=True,
            skip_reason="",
            history=None,
            colors_enabled=False,
        )
        assert "scour" in line

    def test_role_badge_foundation(self):
        """Foundation gates get the wrench badge."""
        line = _format_gate_line(
            "untested-code.py",
            role="foundation",
            in_swab=True,
            in_scour=False,
            is_applicable=True,
            skip_reason="",
            history=None,
            colors_enabled=False,
        )
        assert "🔧" in line

    def test_role_badge_diagnostic(self):
        """Diagnostic gates get the microscope badge."""
        line = _format_gate_line(
            "ignored-feedback",
            role="diagnostic",
            in_swab=True,
            in_scour=False,
            is_applicable=True,
            skip_reason="",
            history=None,
            colors_enabled=False,
        )
        assert "🔬" in line

    def test_role_badge_unknown_empty(self):
        """Unknown role → no badge, no crash.

        Custom gates defined in user config won't have a CheckRole
        classvar until they opt in.  The badge map returns empty
        string — line still formats correctly, just without the
        tier indicator.
        """
        line = _format_gate_line(
            "my-custom-gate",
            role="",
            in_swab=True,
            in_scour=False,
            is_applicable=True,
            skip_reason="",
            history=None,
            colors_enabled=False,
        )
        assert "🔧" not in line
        assert "🔬" not in line
        assert "my-custom-gate" in line


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
            roles={"overconfidence:untested-code.py": "foundation"},
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
            roles={"overconfidence:untested-code.py": "foundation"},
            history={},
            colors_enabled=False,
        )
        out = capsys.readouterr().out
        assert "GATE INVENTORY" in out

    def test_not_applicable_gate(self, capsys):
        """Not applicable gate collapsed into n/a summary line."""
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
            roles={"overconfidence:untested-code.js": "foundation"},
            history={},
            colors_enabled=False,
        )
        out = capsys.readouterr().out
        assert "n/a" in out
        assert "untested-code.js" in out

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
            roles={"overconfidence:untested-code.py": "foundation"},
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
            roles={
                "laziness:sloppy-formatting.py": "foundation",
                "overconfidence:untested-code.py": "foundation",
            },
            history={},
            colors_enabled=False,
        )
        out = capsys.readouterr().out
        # Overconfidence should appear before Laziness
        over_pos = out.index("Overconfidence")
        lazy_pos = out.index("Laziness")
        assert over_pos < lazy_pos

    def test_role_badges_in_inventory(self, capsys):
        """Both role badges appear in the inventory output.

        Foundation and diagnostic tiers are visually distinct — same
        badges as the ConsoleAdapter post-run summary, so users learn
        one legend for the whole tool.
        """
        _print_gate_inventory(
            all_gates=[
                "overconfidence:untested-code.py",
                "deceptiveness:ignored-feedback",
            ],
            swab_gates={"overconfidence:untested-code.py"},
            scour_gates={
                "overconfidence:untested-code.py",
                "deceptiveness:ignored-feedback",
            },
            applicability={
                "overconfidence:untested-code.py": (True, ""),
                "deceptiveness:ignored-feedback": (True, ""),
            },
            roles={
                "overconfidence:untested-code.py": "foundation",
                "deceptiveness:ignored-feedback": "diagnostic",
            },
            history={},
            colors_enabled=False,
        )
        out = capsys.readouterr().out
        assert "🔧" in out  # foundation
        assert "🔬" in out  # diagnostic


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


class TestLatestGateResults:
    """Tests for persisted per-gate status lookup."""

    def test_scour_only_gate_uses_last_scour_even_when_last_swab_is_newer(
        self, tmp_path
    ):
        """Status should not let a newer swab artifact hide scour-only results."""
        sm_dir = tmp_path / ".slopmop"
        sm_dir.mkdir()

        last_scour = sm_dir / "last_scour.json"
        last_scour.write_text(
            json.dumps(
                {
                    "passed_gates": ["myopia:dependency-risk.py"],
                    "results": [],
                }
            )
        )

        last_swab = sm_dir / "last_swab.json"
        last_swab.write_text(
            json.dumps(
                {
                    "passed_gates": ["overconfidence:untested-code.py"],
                    "results": [],
                }
            )
        )

        newer = last_scour.stat().st_mtime + 10
        import os

        os.utime(last_swab, (newer, newer))

        history = {
            "myopia:dependency-risk.py": _stats(results=("failed",)),
        }

        results = _load_latest_gate_results(tmp_path, history)

        assert results["myopia:dependency-risk.py"] == "passed"

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
        assert "Last recorded" in out
        assert "2 gates tracked" in out

    def test_prefers_recent_run_artifact_with_failed_gate_table(self, capsys):
        recent_run = {
            "source_file": "last_scour.json",
            "summary": {
                "passed": 10,
                "failed": 2,
                "warned": 1,
                "errors": 0,
                "skipped": 0,
            },
            "failure_counts": [
                {"name": "myopia:dependency-risk.py", "count": 3},
                {"name": "laziness:dead-code.py", "count": 1},
            ],
        }

        _print_recent_history({}, recent_run)
        out = capsys.readouterr().out

        assert "Source: last_scour.json" in out
        assert "10 passed, 2 failed, 1 warned" in out
        assert "Failed gates: 2" in out
        assert "myopia:dependency-risk.py" in out
        assert "3" in out


class TestBaselineSnapshotStatus:
    """Tests for baseline snapshot status visibility."""

    def test_gather_returns_missing_snapshot_guidance(self, tmp_path):
        data = _gather_baseline_snapshot_data(tmp_path)
        assert data is not None
        assert data["present"] is False
        assert "generate-baseline-snapshot" in data["help"]

    def test_gather_reads_snapshot_metadata(self, tmp_path):
        sm_dir = tmp_path / ".slopmop"
        sm_dir.mkdir()
        (sm_dir / "baseline_snapshot.json").write_text(
            json.dumps(
                {
                    "source_file": "last_scour.json",
                    "captured_at": "2026-03-13T00:00:00+00:00",
                    "failure_fingerprints": ["a", "b", "c"],
                    "source_artifact": {
                        "results": [
                            {
                                "name": "myopia:dependency-risk.py",
                                "status": "failed",
                                "findings": [{"message": "one"}, {"message": "two"}],
                            },
                            {
                                "name": "laziness:dead-code.py",
                                "status": "failed",
                                "output": "dead code",
                            },
                        ]
                    },
                }
            )
        )

        data = _gather_baseline_snapshot_data(tmp_path)

        assert data is not None
        assert data["present"] is True
        assert data["source_file"] == "last_scour.json"
        assert data["tracked_failures"] == 3
        assert data["failed_gates"] == 2
        assert data["failure_counts"] == [
            {"name": "myopia:dependency-risk.py", "count": 2},
            {"name": "laziness:dead-code.py", "count": 1},
        ]

    def test_print_missing_baseline_snapshot_guidance(self, tmp_path, capsys):
        data = _gather_baseline_snapshot_data(tmp_path)
        _print_baseline_snapshot(data)

        out = capsys.readouterr().out
        assert "BASELINE SNAPSHOT" in out
        assert "Missing" in out
        assert "generate-baseline-snapshot" in out

    def test_print_baseline_snapshot(self, tmp_path, capsys):
        sm_dir = tmp_path / ".slopmop"
        sm_dir.mkdir()
        (sm_dir / "baseline_snapshot.json").write_text(
            json.dumps(
                {
                    "source_file": "last_swab.json",
                    "captured_at": "2026-03-13T00:00:00+00:00",
                    "failure_fingerprints": ["a"],
                    "source_artifact": {
                        "results": [
                            {
                                "name": "laziness:dead-code.py",
                                "status": "failed",
                                "output": "dead code",
                            }
                        ]
                    },
                }
            )
        )

        data = _gather_baseline_snapshot_data(tmp_path)
        _print_baseline_snapshot(data)

        out = capsys.readouterr().out
        assert "BASELINE SNAPSHOT" in out
        assert "last_swab.json" in out
        assert "Failed gates: 1" in out
        assert "Tracked failures: 1" in out
        assert "laziness:dead-code.py" in out


class TestBaselineFailureCounts:
    """Tests for failure count extraction from baseline artifacts."""

    def test_counts_findings_per_failed_gate(self):
        artifact = {
            "results": [
                {
                    "name": "a:gate.py",
                    "status": "failed",
                    "findings": [{"message": "one"}, {"message": "two"}],
                },
                {
                    "name": "b:gate.py",
                    "status": "failed",
                    "output": "oops",
                },
                {
                    "name": "c:gate.py",
                    "status": "warned",
                    "findings": [{"message": "ignored"}],
                },
            ]
        }

        result = _failure_counts_from_artifact(artifact)

        assert result == [
            {"name": "a:gate.py", "count": 2},
            {"name": "b:gate.py", "count": 1},
        ]


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


# ---------------------------------------------------------------------------
# Workflow Position
# ---------------------------------------------------------------------------


class TestPrintWorkflowPosition:
    """Tests for the workflow-position section in sm status output."""

    def test_default_state_is_idle(self, tmp_path, capsys):
        """When no state file exists, defaults to S1 IDLE."""
        data = _gather_workflow_data(tmp_path)
        _print_workflow_position(data)
        out = capsys.readouterr().out
        assert "S1" in out
        assert "IDLE" in out
        assert "sm swab" in out

    def test_reads_persisted_state(self, tmp_path, capsys):
        """When a state file exists, displays the persisted state."""
        sm_dir = tmp_path / ".slopmop"
        sm_dir.mkdir()
        (sm_dir / "workflow_state.json").write_text(
            '{"state": "scour_failing", "phase": "maintenance"}'
        )
        data = _gather_workflow_data(tmp_path)
        _print_workflow_position(data)
        out = capsys.readouterr().out
        assert "S4" in out
        assert "SCOUR_FAILING" in out
        assert "sm swab" in out

    def test_phase_displayed(self, tmp_path, capsys):
        """Phase is shown in the output."""
        data = _gather_workflow_data(tmp_path)
        _print_workflow_position(data)
        out = capsys.readouterr().out
        assert "Phase:" in out

    def test_section_header(self, tmp_path, capsys):
        """The section has a header line."""
        data = _gather_workflow_data(tmp_path)
        _print_workflow_position(data)
        out = capsys.readouterr().out
        assert "WORKFLOW POSITION" in out


class TestBuildWorkflowDict:
    """Tests for the JSON workflow section."""

    def test_default_state(self, tmp_path):
        """No state file -> defaults to idle/S1."""
        d = _gather_workflow_data(tmp_path)
        assert d["state"] == "idle"
        assert d["state_id"] == "S1"
        assert d["position"] == 1
        assert "sm swab" in d["next_action"]

    def test_persisted_state(self, tmp_path):
        """Reads persisted state from disk."""
        sm_dir = tmp_path / ".slopmop"
        sm_dir.mkdir()
        (sm_dir / "workflow_state.json").write_text(
            '{"state": "scour_clean", "phase": "maintenance"}'
        )
        d = _gather_workflow_data(tmp_path)
        assert d["state"] == "scour_clean"
        assert d["state_id"] == "S5"
        assert d["position"] == 5
        assert d["phase"] == "maintenance"

    def test_all_keys_present(self, tmp_path):
        """JSON dict has all required keys."""
        d = _gather_workflow_data(tmp_path)
        assert set(d.keys()) == {
            "state",
            "state_id",
            "position",
            "next_action",
            "phase",
        }


# ---------------------------------------------------------------------------
# CI summary — source-of-truth + adapter tests
# ---------------------------------------------------------------------------

_CI_MODULE = "slopmop.cli.ci"


class TestCategorizeChecks:
    """Direct tests for _categorize_checks bucket classification."""

    def test_neutral_bucket_treated_as_completed(self):
        checks = [
            {
                "name": "Cursor Bugbot",
                "bucket": "neutral",
                "link": "",
                "state": "NEUTRAL",
            }
        ]
        completed, in_progress, failed = _categorize_checks(checks)
        assert len(completed) == 1
        assert len(in_progress) == 0
        assert completed[0][0] == "Cursor Bugbot"

    def test_skipping_bucket_with_neutral_state_is_completed(self):
        """Real-world case: gh returns bucket=skipping, state=NEUTRAL for Bugbot."""
        checks = [
            {
                "name": "Cursor Bugbot",
                "bucket": "skipping",
                "link": "https://cursor.com",
                "state": "NEUTRAL",
            }
        ]
        completed, in_progress, failed = _categorize_checks(checks)
        assert len(completed) == 1
        assert len(in_progress) == 0
        assert completed[0][0] == "Cursor Bugbot"

    def test_all_buckets(self):
        checks = [
            {"name": "lint", "bucket": "pass", "link": "", "state": ""},
            {"name": "test", "bucket": "fail", "link": "http://x", "state": ""},
            {"name": "deploy", "bucket": "pending", "link": "", "state": "PENDING"},
            {"name": "bugbot", "bucket": "skipping", "link": "", "state": "NEUTRAL"},
            {"name": "build", "bucket": "cancel", "link": "http://y", "state": ""},
        ]
        completed, in_progress, failed = _categorize_checks(checks)
        assert len(completed) == 2  # pass + skipping/NEUTRAL
        assert len(in_progress) == 1  # pending
        assert len(failed) == 2  # fail + cancel


class TestGatherCiData:
    """Tests for the CI data source-of-truth function."""

    @patch(f"{_CI_MODULE}._detect_pr_number", return_value=None)
    def test_no_pr_returns_none(self, _mock, tmp_path):
        assert _gather_ci_data(tmp_path) is None

    @patch(f"{_CI_MODULE}._categorize_checks", return_value=([], [], []))
    @patch(f"{_CI_MODULE}._fetch_checks", return_value=([], ""))
    @patch(f"{_CI_MODULE}._detect_pr_number", return_value=42)
    def test_empty_checks(self, _pr, _fetch, _cat, tmp_path):
        result = _gather_ci_data(tmp_path)
        assert result == {
            "pr_number": 42,
            "passed": 0,
            "failed": 0,
            "pending": 0,
            "failures": [],
        }

    @patch(f"{_CI_MODULE}._fetch_checks", return_value=(None, "gh not found"))
    @patch(f"{_CI_MODULE}._detect_pr_number", return_value=42)
    def test_fetch_error_returns_none(self, _pr, _fetch, tmp_path):
        assert _gather_ci_data(tmp_path) is None

    @patch(
        f"{_CI_MODULE}._categorize_checks",
        return_value=(
            [("lint", "pass", "", "")],
            [("deploy", "pending", "", "")],
            [("test", "fail", "", ""), ("e2e", "fail", "", "")],
        ),
    )
    @patch(f"{_CI_MODULE}._fetch_checks", return_value=([{"name": "x"}], ""))
    @patch(f"{_CI_MODULE}._detect_pr_number", return_value=99)
    def test_mixed_results(self, _pr, _fetch, _cat, tmp_path):
        d = _gather_ci_data(tmp_path)
        assert d["pr_number"] == 99
        assert d["passed"] == 1
        assert d["failed"] == 2
        assert d["pending"] == 1
        assert d["failures"] == ["test", "e2e"]

    @patch(
        f"{_CI_MODULE}._categorize_checks",
        return_value=(
            [("lint", "pass", "", ""), ("test", "pass", "", "")],
            [],
            [],
        ),
    )
    @patch(f"{_CI_MODULE}._fetch_checks", return_value=([{"name": "x"}], ""))
    @patch(f"{_CI_MODULE}._detect_pr_number", return_value=10)
    def test_all_green(self, _pr, _fetch, _cat, tmp_path):
        d = _gather_ci_data(tmp_path)
        assert d["passed"] == 2
        assert d["failed"] == 0
        assert d["pending"] == 0
        assert d["failures"] == []


class TestPrintCiSummary:
    """Tests for the human-readable CI adapter."""

    def test_none_is_silent(self, capsys):
        _print_ci_summary(None)
        assert capsys.readouterr().out == ""

    def test_zero_total_is_silent(self, capsys):
        _print_ci_summary(
            {
                "pr_number": 1,
                "passed": 0,
                "failed": 0,
                "pending": 0,
                "failures": [],
            }
        )
        assert capsys.readouterr().out == ""

    def test_all_green_shows_sparkle(self, capsys):
        _print_ci_summary(
            {
                "pr_number": 5,
                "passed": 3,
                "failed": 0,
                "pending": 0,
                "failures": [],
            }
        )
        out = capsys.readouterr().out
        assert "PR #5" in out
        assert "3 passed" in out
        assert "✨" in out

    def test_failures_listed(self, capsys):
        _print_ci_summary(
            {
                "pr_number": 7,
                "passed": 2,
                "failed": 2,
                "pending": 0,
                "failures": ["test-unit", "test-e2e"],
            }
        )
        out = capsys.readouterr().out
        assert "2 failed" in out
        assert "test-unit" in out
        assert "test-e2e" in out

    def test_more_than_3_failures_truncated(self, capsys):
        _print_ci_summary(
            {
                "pr_number": 7,
                "passed": 0,
                "failed": 5,
                "pending": 0,
                "failures": ["a", "b", "c", "d", "e"],
            }
        )
        out = capsys.readouterr().out
        assert "a" in out
        assert "b" in out
        assert "c" in out
        assert "2 more" in out

    def test_pending_shown(self, capsys):
        _print_ci_summary(
            {
                "pr_number": 3,
                "passed": 1,
                "failed": 0,
                "pending": 2,
                "failures": [],
            }
        )
        out = capsys.readouterr().out
        assert "2 pending" in out
