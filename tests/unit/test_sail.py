"""Unit tests for the sail command — workflow auto-advance."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import Mock

from slopmop.cli import sail as sail_mod
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
        mock_swab.assert_called_once_with(args)

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

        assert sail_mod.cmd_sail(args) == 0
        out = capsys.readouterr().out
        assert "PR #120" in out
        assert "git push" in out

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
