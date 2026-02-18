"""Tests for the status CLI command.

Tests the parser, dispatch, gate inventory, remediation,
verdict output, and init integration.
"""

import argparse
import json
from unittest.mock import MagicMock, patch

from slopmop.cli.status import (
    _find_other_profiles,
    _print_gate_inventory,
    _print_remediation,
    _print_verdict,
    cmd_status,
    run_status,
)
from slopmop.core.result import CheckResult, CheckStatus, ExecutionSummary
from slopmop.sm import create_parser, main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_registry(
    all_gates=None, aliases=None, expand_alias_return=None, is_alias=True
):
    """Build a mock registry for status tests."""
    mock_reg = MagicMock()
    mock_reg.list_checks.return_value = all_gates or []
    mock_reg.list_aliases.return_value = aliases or {}
    mock_reg.expand_alias.return_value = expand_alias_return or []
    mock_reg.is_alias.return_value = is_alias
    mock_check = MagicMock()
    mock_check.is_applicable.return_value = True
    mock_check.skip_reason.return_value = ""
    mock_reg.get_check.return_value = mock_check
    return mock_reg


def _mock_executor(summary):
    """Build a mock CheckExecutor that returns *summary*."""
    mock_exec = MagicMock()
    mock_exec.run_checks.return_value = summary
    return mock_exec


def _passing_summary(**overrides):
    """Build a MagicMock that looks like a passing ExecutionSummary."""
    s = MagicMock(spec=ExecutionSummary)
    s.all_passed = True
    s.results = []
    s.passed = 0
    s.failed = 0
    s.errors = 0
    s.total_duration = 0.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _failing_summary(**overrides):
    """Build a MagicMock that looks like a failing ExecutionSummary."""
    s = MagicMock(spec=ExecutionSummary)
    s.all_passed = False
    s.results = []
    s.passed = 2
    s.failed = 1
    s.errors = 0
    s.total_duration = 1.5
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


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
        assert args.profile == "pr"

    def test_status_with_profile(self):
        """Status with explicit profile parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["status", "pr"])
        assert args.verb == "status"
        assert args.profile == "pr"

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

    def _run(self, tmp_path, summary=None, **ns_overrides):
        """Helper: run cmd_status with standard mocks."""
        (tmp_path / ".sb_config.json").write_text(json.dumps({}))
        ns = dict(
            profile="commit",
            project_root=str(tmp_path),
            verbose=False,
            quiet=True,
        )
        ns.update(ns_overrides)
        args = argparse.Namespace(**ns)
        summary = summary or _passing_summary()
        executor = _mock_executor(summary)
        registry = _mock_registry()
        with (
            patch(
                "slopmop.cli.status.CheckExecutor",
                return_value=executor,
            ) as cls,
            patch(
                "slopmop.cli.status.get_registry",
                return_value=registry,
            ),
        ):
            result = cmd_status(args)
        return result, cls, executor, registry

    def test_returns_0_when_all_pass(self, tmp_path):
        """Returns 0 when all gates pass."""
        result, *_ = self._run(tmp_path)
        assert result == 0

    def test_returns_1_when_gates_fail(self, tmp_path):
        """Returns 1 when any gate fails."""
        result, *_ = self._run(tmp_path, summary=_failing_summary())
        assert result == 1

    def test_executor_created_without_fail_fast(self, tmp_path):
        """Executor is always created with fail_fast=False."""
        _, cls, *_ = self._run(tmp_path)
        assert cls.call_args[1]["fail_fast"] is False

    def test_executor_called_with_auto_fix_false(self, tmp_path):
        """Status runs with auto_fix=False (read-only)."""
        _, _, executor, _ = self._run(tmp_path)
        assert executor.run_checks.call_args[1]["auto_fix"] is False

    def test_invalid_project_root(self, tmp_path, capsys):
        """Returns 1 for non-existent project root."""
        args = argparse.Namespace(
            profile="commit",
            project_root=str(tmp_path / "nonexistent"),
            verbose=False,
            quiet=False,
        )
        result = cmd_status(args)
        assert result == 1
        assert "not found" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _find_other_profiles helper
# ---------------------------------------------------------------------------


class TestFindOtherProfiles:
    """Tests for _find_other_profiles helper."""

    def test_finds_matching_profiles(self):
        """Returns profiles that include the gate."""
        aliases = {
            "commit": ["overconfidence:py-tests", "laziness:py-lint"],
            "pr": ["overconfidence:py-tests", "pr:comments"],
            "quick": ["laziness:py-lint"],
        }
        result = _find_other_profiles("overconfidence:py-tests", aliases, "commit")
        assert result == ["pr"]

    def test_excludes_current_profile(self):
        """Does not include the current profile."""
        aliases = {
            "commit": ["overconfidence:py-tests"],
            "pr": ["overconfidence:py-tests"],
        }
        result = _find_other_profiles("overconfidence:py-tests", aliases, "commit")
        assert "commit" not in result

    def test_returns_empty_for_unique_gate(self):
        """Returns empty list if gate only in current profile."""
        aliases = {"commit": ["overconfidence:py-tests"], "pr": ["pr:comments"]}
        result = _find_other_profiles("overconfidence:py-tests", aliases, "commit")
        assert result == []


# ---------------------------------------------------------------------------
# Gate inventory output
# ---------------------------------------------------------------------------


class TestPrintGateInventory:
    """Tests for _print_gate_inventory output formatting."""

    def test_passing_gate_in_profile(self, capsys):
        """Passing profile gate shows checkmark."""
        r = CheckResult("overconfidence:py-tests", CheckStatus.PASSED, 1.0)
        _print_gate_inventory(
            all_gates=["overconfidence:py-tests"],
            profile_gates={"overconfidence:py-tests"},
            results_map={"overconfidence:py-tests": r},
            applicability={},
            aliases={},
            profile="commit",
        )
        out = capsys.readouterr().out
        assert "tests" in out
        assert "passing" in out

    def test_failing_gate_in_profile(self, capsys):
        """Failing profile gate shows X mark."""
        r = CheckResult("deceptiveness:py-coverage", CheckStatus.FAILED, 2.0)
        _print_gate_inventory(
            all_gates=["deceptiveness:py-coverage"],
            profile_gates={"deceptiveness:py-coverage"},
            results_map={"deceptiveness:py-coverage": r},
            applicability={},
            aliases={},
            profile="commit",
        )
        out = capsys.readouterr().out
        assert "coverage" in out
        assert "FAILING" in out

    def test_gate_not_in_profile_with_other_profiles(self, capsys):
        """Gate outside profile shows which profiles include it."""
        _print_gate_inventory(
            all_gates=["pr:comments"],
            profile_gates=set(),
            results_map={},
            applicability={"pr:comments": (True, "")},
            aliases={
                "pr": ["pr:comments"],
                "commit": ["overconfidence:py-tests"],
            },
            profile="commit",
        )
        out = capsys.readouterr().out
        assert "not in profile" in out
        assert "pr" in out

    def test_not_applicable_gate(self, capsys):
        """Not applicable gate shows reason."""
        _print_gate_inventory(
            all_gates=["overconfidence:js-tests"],
            profile_gates=set(),
            results_map={},
            applicability={
                "overconfidence:js-tests": (False, "No JavaScript code detected"),
            },
            aliases={},
            profile="commit",
        )
        out = capsys.readouterr().out
        assert "n/a" in out
        assert "No JavaScript code detected" in out

    def test_skipped_gate_in_profile(self, capsys):
        """Skipped profile gate shows reason."""
        r = CheckResult(
            "laziness:js-lint",
            CheckStatus.SKIPPED,
            0.0,
            output="No package.json found",
        )
        _print_gate_inventory(
            all_gates=["laziness:js-lint"],
            profile_gates={"laziness:js-lint"},
            results_map={"laziness:js-lint": r},
            applicability={},
            aliases={},
            profile="pr",
        )
        out = capsys.readouterr().out
        assert "skipped" in out
        assert "No package.json found" in out

    def test_not_applicable_gate_in_profile(self, capsys):
        """NOT_APPLICABLE profile gate shows n/a with reason."""
        r = CheckResult(
            "overconfidence:js-tests",
            CheckStatus.NOT_APPLICABLE,
            0.0,
            output="No package.json found in project root",
        )
        _print_gate_inventory(
            all_gates=["overconfidence:js-tests"],
            profile_gates={"overconfidence:js-tests"},
            results_map={"overconfidence:js-tests": r},
            applicability={},
            aliases={},
            profile="pr",
        )
        out = capsys.readouterr().out
        assert "n/a" in out
        assert "No package.json found in project root" in out

    def test_shows_category_header(self, capsys):
        """Inventory groups gates under category headers."""
        r = CheckResult("overconfidence:py-tests", CheckStatus.PASSED, 0.5)
        _print_gate_inventory(
            all_gates=["overconfidence:py-tests"],
            profile_gates={"overconfidence:py-tests"},
            results_map={"overconfidence:py-tests": r},
            applicability={},
            aliases={},
            profile="commit",
        )
        out = capsys.readouterr().out
        assert "Overconfidence" in out

    def test_inventory_header(self, capsys):
        """Inventory section has GATE INVENTORY header."""
        _print_gate_inventory(
            all_gates=["overconfidence:py-tests"],
            profile_gates={"overconfidence:py-tests"},
            results_map={
                "overconfidence:py-tests": CheckResult(
                    "overconfidence:py-tests", CheckStatus.PASSED, 0.5
                )
            },
            applicability={},
            aliases={},
            profile="commit",
        )
        out = capsys.readouterr().out
        assert "GATE INVENTORY" in out

    def test_error_gate_in_profile(self, capsys):
        """Errored gate in profile shows error marker."""
        r = CheckResult(
            "myopia:security-scan",
            CheckStatus.ERROR,
            0.1,
            error="bandit not installed",
        )
        _print_gate_inventory(
            all_gates=["myopia:security-scan"],
            profile_gates={"myopia:security-scan"},
            results_map={"myopia:security-scan": r},
            applicability={},
            aliases={},
            profile="commit",
        )
        out = capsys.readouterr().out
        assert "ERROR" in out


# ---------------------------------------------------------------------------
# Remediation output
# ---------------------------------------------------------------------------


class TestPrintRemediation:
    """Tests for _print_remediation output."""

    def test_no_remediation_when_all_pass(self, capsys):
        """No remediation printed when all gates pass."""
        results = {
            "overconfidence:py-tests": CheckResult(
                "overconfidence:py-tests", CheckStatus.PASSED, 1.0
            ),
        }
        _print_remediation(results)
        assert "REMEDIATION" not in capsys.readouterr().out

    def test_remediation_for_failing_gate(self, capsys):
        """Failing gate shows remediation with verify command."""
        results = {
            "deceptiveness:py-coverage": CheckResult(
                "deceptiveness:py-coverage",
                CheckStatus.FAILED,
                1.0,
                error="Coverage below 80% threshold",
                fix_suggestion="Add tests for uncovered modules",
            ),
        }
        _print_remediation(results)
        out = capsys.readouterr().out
        assert "REMEDIATION" in out
        assert "deceptiveness:py-coverage" in out
        assert "Coverage below 80% threshold" in out
        assert "Add tests for uncovered modules" in out
        assert "scripts/sm validate deceptiveness:py-coverage" in out

    def test_remediation_for_errored_gate(self, capsys):
        """Errored gate shows remediation."""
        results = {
            "myopia:security-scan": CheckResult(
                "myopia:security-scan",
                CheckStatus.ERROR,
                0.1,
                error="bandit not installed",
            ),
        }
        _print_remediation(results)
        out = capsys.readouterr().out
        assert "REMEDIATION" in out
        assert "bandit not installed" in out


# ---------------------------------------------------------------------------
# Verdict output
# ---------------------------------------------------------------------------


class TestPrintVerdict:
    """Tests for _print_verdict output."""

    def test_clean_verdict(self, capsys):
        """All passing shows no AI slop detected."""
        results = [
            CheckResult("overconfidence:py-tests", CheckStatus.PASSED, 1.0),
            CheckResult("deceptiveness:py-coverage", CheckStatus.PASSED, 0.5),
        ]
        summary = ExecutionSummary.from_results(results, 1.5)
        _print_verdict(summary)
        assert "no AI slop detected" in capsys.readouterr().out

    def test_failing_verdict(self, capsys):
        """Failures show count of passing/failing."""
        results = [
            CheckResult("overconfidence:py-tests", CheckStatus.PASSED, 1.0),
            CheckResult("deceptiveness:py-coverage", CheckStatus.FAILED, 0.5),
        ]
        summary = ExecutionSummary.from_results(results, 1.5)
        _print_verdict(summary)
        out = capsys.readouterr().out
        assert "1/2 gates passing" in out
        assert "1 failing" in out

    def test_skipped_excluded_from_count(self, capsys):
        """Skipped gates are not counted in the total."""
        results = [
            CheckResult("overconfidence:py-tests", CheckStatus.PASSED, 1.0),
            CheckResult(
                "overconfidence:js-tests",
                CheckStatus.SKIPPED,
                0.0,
                output="no JS",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        _print_verdict(summary)
        assert "no AI slop detected" in capsys.readouterr().out

    def test_not_applicable_excluded_from_count(self, capsys):
        """NOT_APPLICABLE gates are not counted in the total."""
        results = [
            CheckResult("overconfidence:py-tests", CheckStatus.PASSED, 1.0),
            CheckResult(
                "overconfidence:js-tests",
                CheckStatus.NOT_APPLICABLE,
                0.0,
                output="No package.json found",
            ),
        ]
        summary = ExecutionSummary.from_results(results, 1.0)
        _print_verdict(summary)
        assert "no AI slop detected" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# run_status direct invocation
# ---------------------------------------------------------------------------


class TestRunStatus:
    """Tests for the run_status() function called directly."""

    def _run(self, tmp_path, summary=None, profile="commit"):
        """Helper: call run_status with standard mocks."""
        (tmp_path / ".sb_config.json").write_text(json.dumps({}))
        summary = summary or _passing_summary()
        executor = _mock_executor(summary)
        registry = _mock_registry()
        with (
            patch(
                "slopmop.cli.status.CheckExecutor",
                return_value=executor,
            ) as cls,
            patch(
                "slopmop.cli.status.get_registry",
                return_value=registry,
            ),
        ):
            result = run_status(project_root=str(tmp_path), profile=profile)
        return result, cls, executor, registry

    def test_returns_0_when_all_pass(self, tmp_path):
        """run_status returns 0 when all gates pass."""
        result, *_ = self._run(tmp_path)
        assert result == 0

    def test_returns_1_when_gates_fail(self, tmp_path):
        """run_status returns 1 when gates fail."""
        result, *_ = self._run(tmp_path, summary=_failing_summary())
        assert result == 1

    def test_invalid_project_root(self, tmp_path, capsys):
        """run_status returns 1 for non-existent path."""
        result = run_status(project_root=str(tmp_path / "nonexistent"))
        assert result == 1
        assert "not found" in capsys.readouterr().out

    def test_accepts_profile(self, tmp_path):
        """run_status passes the profile through to run_checks."""
        _, _, executor, _ = self._run(tmp_path, profile="pr")
        call_kwargs = executor.run_checks.call_args[1]
        assert call_kwargs["check_names"] == ["pr"]


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
