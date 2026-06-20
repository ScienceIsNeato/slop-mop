"""Unit tests for the sail command — workflow auto-advance."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from slopmop.cli import sail as sail_mod
from slopmop.cli.scan_triage import ARTIFACT_NAME, WORKFLOW_NAME
from slopmop.workflow.state_machine import SailMode, WorkflowState


def _base_args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=str(tmp_path),
        verbose=False,
        quiet=False,
        json_output=False,
        static=False,
    )


class TestSailDispatch:
    """Each workflow state dispatches to the correct action."""

    @pytest.fixture(autouse=True)
    def _onboarded(self, monkeypatch):
        """Treat every repo in this class as already onboarded."""
        monkeypatch.setattr(sail_mod, "_onboard_status", lambda _: "onboarded")

    def test_idle_runs_swab(self, monkeypatch, tmp_path: Path):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.IDLE)
        mock_swab = Mock(return_value=0)
        monkeypatch.setattr("slopmop.cli.cmd_swab", mock_swab)

        assert sail_mod.cmd_sail(args) == 0
        mock_swab.assert_called_once()
        enriched = mock_swab.call_args[0][0]
        assert hasattr(enriched, "no_fail_fast")
        assert hasattr(enriched, "no_auto_fix")
        assert enriched.project_root == str(tmp_path)

    def test_swab_failing_runs_swab(self, monkeypatch, tmp_path: Path):
        args = _base_args(tmp_path)
        monkeypatch.setattr(
            sail_mod, "read_state", lambda _: WorkflowState.SWAB_FAILING
        )
        mock_swab = Mock(return_value=1)
        monkeypatch.setattr("slopmop.cli.cmd_swab", mock_swab)

        assert sail_mod.cmd_sail(args) == 1
        mock_swab.assert_called_once()

    def test_swab_clean_with_dirty_tree_tells_user_to_commit(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.SWAB_CLEAN)
        monkeypatch.setattr(sail_mod, "_has_uncommitted_changes", lambda _: True)

        assert sail_mod.cmd_sail(args) == 0
        out = capsys.readouterr().out
        assert "Commit your changes" in out

    def test_swab_clean_with_clean_tree_runs_scour(self, monkeypatch, tmp_path: Path):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.SWAB_CLEAN)
        monkeypatch.setattr(sail_mod, "_has_uncommitted_changes", lambda _: False)
        mock_scour = Mock(return_value=0)
        monkeypatch.setattr("slopmop.cli.cmd_scour", mock_scour)

        assert sail_mod.cmd_sail(args) == 0
        mock_scour.assert_called_once()

    def test_scour_failing_runs_swab(self, monkeypatch, tmp_path: Path):
        args = _base_args(tmp_path)
        monkeypatch.setattr(
            sail_mod, "read_state", lambda _: WorkflowState.SCOUR_FAILING
        )
        mock_swab = Mock(return_value=0)
        monkeypatch.setattr("slopmop.cli.cmd_swab", mock_swab)

        assert sail_mod.cmd_sail(args) == 0
        mock_swab.assert_called_once()

    def test_scour_clean_with_pr_suggests_push(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.SCOUR_CLEAN)
        monkeypatch.setattr(sail_mod, "_get_pr_number", lambda _: 120)
        monkeypatch.setattr(sail_mod, "_has_unpushed_commits", lambda _: True)

        assert sail_mod.cmd_sail(args) == 0
        out = capsys.readouterr().out
        assert "PR #120" in out
        assert "git push" in out

    def test_scour_clean_with_pushed_pr_runs_buff_and_heals_state(
        self, monkeypatch, tmp_path: Path
    ):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.SCOUR_CLEAN)
        monkeypatch.setattr(sail_mod, "_get_pr_number", lambda _: 42)
        monkeypatch.setattr(sail_mod, "_has_unpushed_commits", lambda _: False)
        write_state = Mock()
        monkeypatch.setattr(sail_mod, "write_state", write_state)
        monkeypatch.setattr("slopmop.cli.cmd_scour", Mock(return_value=0))
        mock_buff = Mock(return_value=0)
        monkeypatch.setattr("slopmop.cli.cmd_buff", mock_buff)

        assert sail_mod.cmd_sail(args) == 0
        write_state.assert_called_once_with(tmp_path, WorkflowState.PR_OPEN)
        mock_buff.assert_called_once()
        call_args = mock_buff.call_args[0][0]
        assert call_args.pr_or_action == "watch"
        assert call_args.action_args == ["42"]

    def test_scour_clean_without_pr_suggests_create(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.SCOUR_CLEAN)
        monkeypatch.setattr(sail_mod, "_get_pr_number", lambda _: None)

        assert sail_mod.cmd_sail(args) == 0
        out = capsys.readouterr().out
        assert "gh pr create" in out

    def test_pr_open_runs_buff(self, monkeypatch, tmp_path: Path):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.PR_OPEN)
        monkeypatch.setattr(sail_mod, "_get_pr_number", lambda _: 42)
        monkeypatch.setattr("slopmop.cli.cmd_scour", Mock(return_value=0))
        mock_buff = Mock(return_value=0)
        monkeypatch.setattr("slopmop.cli.cmd_buff", mock_buff)

        assert sail_mod.cmd_sail(args) == 0
        mock_buff.assert_called_once()
        # Verify it called buff in watch mode with the PR number
        call_args = mock_buff.call_args[0][0]
        assert call_args.pr_or_action == "watch"
        assert call_args.action_args == ["42"]

    def test_buff_failing_runs_buff(self, monkeypatch, tmp_path: Path):
        args = _base_args(tmp_path)
        monkeypatch.setattr(
            sail_mod, "read_state", lambda _: WorkflowState.BUFF_FAILING
        )
        monkeypatch.setattr(sail_mod, "_get_pr_number", lambda _: 99)
        mock_buff = Mock(return_value=1)
        monkeypatch.setattr("slopmop.cli.cmd_buff", mock_buff)

        assert sail_mod.cmd_sail(args) == 1
        mock_buff.assert_called_once()
        call_args = mock_buff.call_args[0][0]
        assert call_args.workflow == WORKFLOW_NAME
        assert call_args.artifact == ARTIFACT_NAME

    def test_pr_ready_reports_ready_for_human_review(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.PR_READY)
        monkeypatch.setattr(sail_mod, "_get_pr_number", lambda _: 42)
        mock_buff = Mock(return_value=0)
        monkeypatch.setattr("slopmop.cli.cmd_buff", mock_buff)
        monkeypatch.setattr(sail_mod, "write_sail_mode", Mock())

        assert sail_mod.cmd_sail(args) == 0
        out = capsys.readouterr().out
        assert "human review" in out
        mock_buff.assert_called_once()
        call_args = mock_buff.call_args[0][0]
        assert call_args.pr_or_action == "watch"

    def test_none_state_defaults_to_idle(self, monkeypatch, tmp_path: Path):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: None)
        mock_swab = Mock(return_value=0)
        monkeypatch.setattr("slopmop.cli.cmd_swab", mock_swab)

        assert sail_mod.cmd_sail(args) == 0
        mock_swab.assert_called_once()


class TestSailOnboarding:
    """sail detects unonboarded repos and gives the right guidance."""

    def test_fresh_repo_prints_guidance_and_returns_1(self, capsys, tmp_path: Path):
        args = _base_args(tmp_path)
        # tmp_path has no .slopmop/ and no .sb_config.json

        result = sail_mod.cmd_sail(args)

        assert result == 1
        out = capsys.readouterr().out
        assert "sm refit --start" in out

    def test_init_done_but_no_refit_prints_guidance_and_returns_1(
        self, capsys, tmp_path: Path
    ):
        args = _base_args(tmp_path)
        (tmp_path / ".sb_config.json").write_text("{}")

        result = sail_mod.cmd_sail(args)

        assert result == 1
        out = capsys.readouterr().out
        assert "sm refit --start" in out

    def test_onboarded_repo_proceeds_normally(self, monkeypatch, tmp_path: Path):
        args = _base_args(tmp_path)
        (tmp_path / ".slopmop").mkdir()
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.IDLE)
        mock_swab = Mock(return_value=0)
        monkeypatch.setattr("slopmop.cli.cmd_swab", mock_swab)

        assert sail_mod.cmd_sail(args) == 0
        mock_swab.assert_called_once()

    def test_onboard_status_fresh(self, tmp_path: Path):
        assert sail_mod._onboard_status(tmp_path) == "fresh"

    def test_onboard_status_init_done(self, tmp_path: Path):
        (tmp_path / ".sb_config.json").write_text("{}")
        assert sail_mod._onboard_status(tmp_path) == "init_done"

    def test_onboard_status_onboarded(self, tmp_path: Path):
        (tmp_path / ".slopmop").mkdir()
        assert sail_mod._onboard_status(tmp_path) == "onboarded"

    def test_slopmop_dir_takes_precedence_over_config(self, tmp_path: Path):
        """When both .slopmop/ and .sb_config.json exist, repo is onboarded."""
        (tmp_path / ".slopmop").mkdir()
        (tmp_path / ".sb_config.json").write_text("{}")
        assert sail_mod._onboard_status(tmp_path) == "onboarded"


class TestSwabArgs:
    """Verify _swab_args provides every attribute that validate expects."""

    _REQUIRED_ATTRS = (
        "quality_gates",
        "no_auto_fix",
        "no_fail_fast",
        "no_cache",
        "sarif",
        "json_output",
        "json_file",
        "output_file",
        "verbose",
        "quiet",
        "static",
        "swabbing_timeout",
        "clear_history",
        "ignore_baseline_failures",
    )

    def test_all_validation_attrs_present(self, tmp_path: Path):
        """Sail's minimal namespace must be enriched with all swab attrs."""
        base = _base_args(tmp_path)
        enriched = sail_mod._swab_args(base)
        for attr in self._REQUIRED_ATTRS:
            assert hasattr(enriched, attr), f"_swab_args missing attribute: {attr}"

    def test_preserves_caller_overrides(self, tmp_path: Path):
        """Attributes already on the source namespace survive enrichment."""
        base = _base_args(tmp_path)
        base.verbose = True
        base.static = True
        enriched = sail_mod._swab_args(base)
        assert enriched.verbose is True
        assert enriched.static is True

    def test_does_not_mutate_original(self, tmp_path: Path):
        base = _base_args(tmp_path)
        enriched = sail_mod._swab_args(base)
        enriched.no_fail_fast = True
        assert not hasattr(base, "no_fail_fast") or base.no_fail_fast is not True


class TestSailStateReconciliation:
    def test_has_unpushed_commits_returns_true_when_upstream_missing(
        self, monkeypatch, tmp_path: Path
    ):
        monkeypatch.setattr(
            sail_mod.subprocess,
            "run",
            Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr="")),
        )

        assert sail_mod._has_unpushed_commits(tmp_path) is True

    def test_has_unpushed_commits_returns_true_when_divergence_check_fails(
        self, monkeypatch, tmp_path: Path
    ):
        monkeypatch.setattr(
            sail_mod.subprocess,
            "run",
            Mock(
                side_effect=[
                    SimpleNamespace(returncode=0, stdout="origin/friction\n"),
                    SimpleNamespace(returncode=1, stdout="", stderr="boom"),
                ]
            ),
        )

        assert sail_mod._has_unpushed_commits(tmp_path) is True

    def test_has_unpushed_commits_returns_true_on_malformed_divergence_output(
        self, monkeypatch, tmp_path: Path
    ):
        monkeypatch.setattr(
            sail_mod.subprocess,
            "run",
            Mock(
                side_effect=[
                    SimpleNamespace(returncode=0, stdout="origin/friction\n"),
                    SimpleNamespace(returncode=0, stdout="garbled"),
                ]
            ),
        )

        assert sail_mod._has_unpushed_commits(tmp_path) is True

    def test_has_unpushed_commits_returns_true_on_non_numeric_ahead_count(
        self, monkeypatch, tmp_path: Path
    ):
        monkeypatch.setattr(
            sail_mod.subprocess,
            "run",
            Mock(
                side_effect=[
                    SimpleNamespace(returncode=0, stdout="origin/friction\n"),
                    SimpleNamespace(returncode=0, stdout="0 nope"),
                ]
            ),
        )

        assert sail_mod._has_unpushed_commits(tmp_path) is True

    def test_has_unpushed_commits_returns_false_when_head_matches_upstream(
        self, monkeypatch, tmp_path: Path
    ):
        monkeypatch.setattr(
            sail_mod.subprocess,
            "run",
            Mock(
                side_effect=[
                    SimpleNamespace(returncode=0, stdout="origin/friction\n"),
                    SimpleNamespace(returncode=0, stdout="0 0"),
                ]
            ),
        )

        assert sail_mod._has_unpushed_commits(tmp_path) is False

    def test_reconcile_runtime_state_keeps_non_scour_states(
        self, monkeypatch, tmp_path: Path
    ):
        pr_lookup = Mock(side_effect=AssertionError("should not be called"))
        monkeypatch.setattr(sail_mod, "_get_pr_number", pr_lookup)

        state = sail_mod._reconcile_runtime_state(WorkflowState.PR_READY, tmp_path)

        assert state == WorkflowState.PR_READY

    def test_reconcile_runtime_state_keeps_scour_clean_without_pr(
        self, monkeypatch, tmp_path: Path
    ):
        monkeypatch.setattr(sail_mod, "_get_pr_number", lambda _: None)

        state = sail_mod._reconcile_runtime_state(
            WorkflowState.SCOUR_CLEAN,
            tmp_path,
        )

        assert state == WorkflowState.SCOUR_CLEAN


class TestSailMode:
    """Sailing mode is activated on entry and drives mode-aware output."""

    @pytest.fixture(autouse=True)
    def _onboarded(self, monkeypatch):
        monkeypatch.setattr(sail_mod, "_onboard_status", lambda _: "onboarded")

    def test_cmd_sail_activates_sailing_mode(self, monkeypatch, tmp_path: Path):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.IDLE)
        monkeypatch.setattr("slopmop.cli.cmd_swab", Mock(return_value=0))
        write_sail_mode = Mock()
        monkeypatch.setattr(sail_mod, "write_sail_mode", write_sail_mode)

        sail_mod.cmd_sail(args)

        write_sail_mode.assert_any_call(tmp_path, SailMode.SAILING)

    def test_swab_clean_uncommitted_gives_exact_commit_command(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.SWAB_CLEAN)
        monkeypatch.setattr(sail_mod, "_has_uncommitted_changes", lambda _: True)
        monkeypatch.setattr(sail_mod, "write_sail_mode", Mock())

        assert sail_mod.cmd_sail(args) == 0
        out = capsys.readouterr().out
        assert "git add -A" in out
        assert "git commit" in out
        assert "sm sail" in out

    def test_scour_clean_no_pr_gives_exact_push_and_create_commands(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.SCOUR_CLEAN)
        monkeypatch.setattr(sail_mod, "_get_pr_number", lambda _: None)
        monkeypatch.setattr(sail_mod, "write_sail_mode", Mock())

        assert sail_mod.cmd_sail(args) == 0
        out = capsys.readouterr().out
        assert "git push -u origin HEAD" in out
        assert "gh pr create --fill" in out
        assert "sm sail" in out

    def test_scour_clean_with_pr_gives_exact_push_command(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.SCOUR_CLEAN)
        monkeypatch.setattr(sail_mod, "_get_pr_number", lambda _: 77)
        monkeypatch.setattr(sail_mod, "_has_unpushed_commits", lambda _: True)
        monkeypatch.setattr(sail_mod, "write_sail_mode", Mock())

        assert sail_mod.cmd_sail(args) == 0
        out = capsys.readouterr().out
        assert "git push" in out
        assert "sm sail" in out

    def test_pr_ready_resets_mode_to_tacking(self, monkeypatch, tmp_path: Path):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.PR_READY)
        monkeypatch.setattr(sail_mod, "_get_pr_number", lambda _: 42)
        monkeypatch.setattr("slopmop.cli.cmd_buff", Mock(return_value=0))
        write_sail_mode = Mock()
        monkeypatch.setattr(sail_mod, "write_sail_mode", write_sail_mode)

        sail_mod.cmd_sail(args)

        write_sail_mode.assert_any_call(tmp_path, SailMode.TACKING)


class TestSailDrive:
    """sm sail drives through consecutive tool-steps in one invocation,
    stopping only when the workflow parks on an agent/human action or reaches
    PR_READY."""

    @pytest.fixture(autouse=True)
    def _onboarded(self, monkeypatch):
        monkeypatch.setattr(sail_mod, "_onboard_status", lambda _: "onboarded")
        monkeypatch.setattr(sail_mod, "write_sail_mode", Mock())
        monkeypatch.setattr(sail_mod, "write_state", Mock())
        # reconcile is identity here — we drive state purely via the holder.
        monkeypatch.setattr(
            sail_mod, "_reconcile_runtime_state", lambda state, _root: state
        )

    def _drive(self, monkeypatch, start, transitions):
        """Wire a state holder + mock handlers.

        ``transitions`` maps a state to the state it advances to (or ``None``
        to park). Returns the ordered list of states whose handlers ran.
        """
        holder = {"state": start}
        monkeypatch.setattr(sail_mod, "read_state", lambda _: holder["state"])

        calls: list[WorkflowState] = []

        def make_handler(advance_to):
            def handler(_args, _root):
                calls.append(holder["state"])
                if advance_to is not None:
                    holder["state"] = advance_to
                return 0

            return handler

        handlers = {
            state: make_handler(advance_to) for state, advance_to in transitions.items()
        }
        monkeypatch.setattr(sail_mod, "_STATE_HANDLERS", handlers)
        return calls

    def test_chains_swab_scour_until_parked_at_push(self, monkeypatch, tmp_path: Path):
        # After a fix, one `sm sail` runs swab → scour and parks at the push step.
        calls = self._drive(
            monkeypatch,
            WorkflowState.SCOUR_FAILING,
            {
                WorkflowState.SCOUR_FAILING: WorkflowState.SWAB_CLEAN,
                WorkflowState.SWAB_CLEAN: WorkflowState.SCOUR_CLEAN,
                WorkflowState.SCOUR_CLEAN: None,  # parks — agent must push
            },
        )
        assert sail_mod.cmd_sail(_base_args(tmp_path)) == 0
        assert calls == [
            WorkflowState.SCOUR_FAILING,
            WorkflowState.SWAB_CLEAN,
            WorkflowState.SCOUR_CLEAN,
        ]

    def test_stops_at_pr_ready_without_looping_past_it(
        self, monkeypatch, tmp_path: Path
    ):
        # PR_READY is terminal: its handler runs, then sail returns even if the
        # handler would otherwise advance the state.
        calls = self._drive(
            monkeypatch,
            WorkflowState.PR_OPEN,
            {
                WorkflowState.PR_OPEN: WorkflowState.PR_READY,
                WorkflowState.PR_READY: WorkflowState.IDLE,  # must NOT be followed
            },
        )
        assert sail_mod.cmd_sail(_base_args(tmp_path)) == 0
        assert calls == [WorkflowState.PR_OPEN, WorkflowState.PR_READY]

    def test_parks_immediately_when_state_does_not_advance(
        self, monkeypatch, tmp_path: Path
    ):
        # A handler that needs the agent (e.g. failing gate) doesn't advance the
        # state, so the drive stops after one step.
        calls = self._drive(
            monkeypatch,
            WorkflowState.SWAB_FAILING,
            {WorkflowState.SWAB_FAILING: None},
        )
        assert sail_mod.cmd_sail(_base_args(tmp_path)) == 0
        assert calls == [WorkflowState.SWAB_FAILING]

    def test_cycle_guard_bails_on_ping_pong(self, monkeypatch, tmp_path: Path):
        # If the machine ping-pongs between two states, the cycle guard stops it
        # rather than spinning to the step cap.
        calls = self._drive(
            monkeypatch,
            WorkflowState.SWAB_CLEAN,
            {
                WorkflowState.SWAB_CLEAN: WorkflowState.SCOUR_FAILING,
                WorkflowState.SCOUR_FAILING: WorkflowState.SWAB_CLEAN,
            },
        )
        assert sail_mod.cmd_sail(_base_args(tmp_path)) == 0
        # Each state's handler runs once; the revisit is caught before a third.
        assert calls == [WorkflowState.SWAB_CLEAN, WorkflowState.SCOUR_FAILING]

    def test_unknown_state_falls_back_to_swab(self, monkeypatch, tmp_path: Path):
        # A state with no registered handler falls back to swab rather than
        # crashing — the drive's safety net.
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.IDLE)
        monkeypatch.setattr(sail_mod, "_STATE_HANDLERS", {})  # no handler for IDLE
        mock_swab = Mock(return_value=0)
        monkeypatch.setattr("slopmop.cli.cmd_swab", mock_swab)

        assert sail_mod.cmd_sail(_base_args(tmp_path)) == 0
        mock_swab.assert_called_once()
