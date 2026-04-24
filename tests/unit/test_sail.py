"""Unit tests for the sail command — workflow auto-advance."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from slopmop.cli import sail as sail_mod
from slopmop.cli.scan_triage import ARTIFACT_NAME, WORKFLOW_NAME
from slopmop.workflow.state_machine import WorkflowState


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
        mock_buff = Mock(return_value=0)
        monkeypatch.setattr("slopmop.cli.cmd_buff", mock_buff)

        assert sail_mod.cmd_sail(args) == 0
        write_state.assert_called_once_with(tmp_path, WorkflowState.PR_OPEN)
        mock_buff.assert_called_once()
        call_args = mock_buff.call_args[0][0]
        assert call_args.pr_or_action == "42"
        assert call_args.workflow == WORKFLOW_NAME
        assert call_args.artifact == ARTIFACT_NAME

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
        mock_buff = Mock(return_value=0)
        monkeypatch.setattr("slopmop.cli.cmd_buff", mock_buff)

        assert sail_mod.cmd_sail(args) == 0
        mock_buff.assert_called_once()
        # Verify it passed the PR number
        call_args = mock_buff.call_args[0][0]
        assert call_args.pr_or_action == "42"
        assert call_args.workflow == WORKFLOW_NAME
        assert call_args.artifact == ARTIFACT_NAME

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

    def test_pr_ready_reports_ready_to_land(self, monkeypatch, capsys, tmp_path: Path):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: WorkflowState.PR_READY)

        assert sail_mod.cmd_sail(args) == 0
        out = capsys.readouterr().out
        assert "ready to land" in out
        assert "finalize" in out

    def test_none_state_defaults_to_idle(self, monkeypatch, tmp_path: Path):
        args = _base_args(tmp_path)
        monkeypatch.setattr(sail_mod, "read_state", lambda _: None)
        mock_swab = Mock(return_value=0)
        monkeypatch.setattr("slopmop.cli.cmd_swab", mock_swab)

        assert sail_mod.cmd_sail(args) == 0
        mock_swab.assert_called_once()


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
